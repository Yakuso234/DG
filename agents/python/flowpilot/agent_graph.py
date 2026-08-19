"""P3 单 LangGraph 主图：分诊、调查、提案与风险复核。"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flowpilot.domain.executor import risk_of, validate_params
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.sw_video_ops import SwVideoOpsGateway, status_to_evidence


class FlowPilotGraphState(TypedDict, total=False):
    ticket_id: str
    creator_id: int
    video_id: int
    trace_id: str
    triage: dict[str, Any]
    evidence: list[dict[str, Any]]
    proposal: dict[str, Any]
    risk_review: dict[str, Any]
    approval: dict[str, Any]
    steps: list[str]


def initial_state(*, ticket_id: str, creator_id: int, video_id: int, trace_id: str) -> FlowPilotGraphState:
    return {"ticket_id": ticket_id, "creator_id": creator_id, "video_id": video_id, "trace_id": trace_id, "steps": []}


def _steps(state: FlowPilotGraphState, step: str) -> list[str]:
    return [*state.get("steps", []), step]


def build_graph(gateway: SwVideoOpsGateway, *, checkpointer: Any = None, require_approval: bool = False):
    """构建无 LLM、可测试的 P3 主图；模型替换不改变领域校验边界。"""

    async def triage(state: FlowPilotGraphState) -> dict[str, Any]:
        return {"triage": {"category": "video_processing_stalled", "priority": 4}, "steps": _steps(state, "triage")}

    async def investigate(state: FlowPilotGraphState) -> dict[str, Any]:
        snapshot = await gateway.get_video_processing_status(
            creator_id=state["creator_id"], video_id=state["video_id"], trace_id=state["trace_id"]
        )
        evidence = status_to_evidence(ticket_id=state["ticket_id"], snapshot=snapshot)
        return {"evidence": [evidence.to_dict()], "steps": _steps(state, "investigation")}

    async def resolution(state: FlowPilotGraphState) -> dict[str, Any]:
        evidence = state["evidence"]
        processing_status = evidence[0]["data"]["processing_status"]
        if processing_status != "PROCESSING":
            raise ValueError(f"当前 P3 只为 PROCESSING 卡住场景生成恢复提案，实际为 {processing_status!r}")
        proposal = ActionProposal(
            id=str(uuid.uuid4()),
            ticket_id=state["ticket_id"],
            action="restart_pipeline",
            params={"ticket_id": state["ticket_id"]},
            evidence_ids=[evidence[0]["id"]],
            risk="high",
            created_by="flowpilot-resolution-agent",
            created_at=utc_now_iso(),
        )
        return {"proposal": proposal.to_dict(), "steps": _steps(state, "resolution")}

    async def risk_review(state: FlowPilotGraphState) -> dict[str, Any]:
        proposal = ActionProposal.from_dict(state["proposal"])
        validate_params(proposal.action, proposal.params)
        risk = risk_of(proposal.action).value
        return {
            "risk_review": {"approved_for_human_review": True, "authoritative_risk": risk},
            "steps": _steps(state, "risk_review"),
        }

    async def await_approval(state: FlowPilotGraphState) -> dict[str, Any]:
        decision = interrupt(
            {"ticket_id": state["ticket_id"], "proposal": state["proposal"], "risk": state["risk_review"]}
        )
        if decision not in ("approved", "denied", "modified"):
            raise ValueError("审批恢复值只能是 approved、denied 或 modified")
        return {"approval": {"decision": decision}, "steps": _steps(state, "approval")}

    builder = StateGraph(FlowPilotGraphState)
    builder.add_node("triage", triage)
    builder.add_node("investigation", investigate)
    builder.add_node("resolution", resolution)
    builder.add_node("risk_review", risk_review)
    if require_approval:
        builder.add_node("await_approval", await_approval)
    builder.add_edge(START, "triage")
    builder.add_edge("triage", "investigation")
    builder.add_edge("investigation", "resolution")
    builder.add_edge("resolution", "risk_review")
    if require_approval:
        builder.add_edge("risk_review", "await_approval")
        builder.add_edge("await_approval", END)
    else:
        builder.add_edge("risk_review", END)
    return builder.compile(checkpointer=checkpointer)
