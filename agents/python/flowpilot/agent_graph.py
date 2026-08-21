"""P3 单 LangGraph 主图：分诊、调查、提案与风险复核。"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION, risk_of, validate_params
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.structured_model import (
    ModelOutputValidationError,
    ResolutionModelInput,
    StructuredFlowPilotModel,
    TriageModelInput,
)
from flowpilot.sw_video_ops import SwVideoOpsGateway, status_to_evidence


class FlowPilotGraphState(TypedDict, total=False):
    ticket_id: str
    creator_id: int
    video_id: int
    trace_id: str
    triage: dict[str, Any]
    resolution_suggestion: dict[str, Any]
    evidence: list[dict[str, Any]]
    proposal: dict[str, Any]
    risk_review: dict[str, Any]
    approval: dict[str, Any]
    steps: list[str]


class ResolutionNotApplicableError(ValueError):
    """当前证据不满足自动生成恢复提案的确定性前置条件。"""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def initial_state(*, ticket_id: str, creator_id: int, video_id: int, trace_id: str) -> FlowPilotGraphState:
    return {"ticket_id": ticket_id, "creator_id": creator_id, "video_id": video_id, "trace_id": trace_id, "steps": []}


def _steps(state: FlowPilotGraphState, step: str) -> list[str]:
    return [*state.get("steps", []), step]


def build_graph(
    gateway: SwVideoOpsGateway,
    *,
    checkpointer: Any = None,
    require_approval: bool = False,
    model: StructuredFlowPilotModel | None = None,
):
    """构建主图；可选模型只提供受控建议，领域校验不交给模型。"""

    async def triage(state: FlowPilotGraphState) -> dict[str, Any]:
        if model is None:
            return {
                "triage": {"category": "video_processing_stalled", "priority": 4, "source": "deterministic"},
                "steps": _steps(state, "triage"),
            }
        output = await model.triage(
            TriageModelInput(
                ticket_id=state["ticket_id"],
                creator_id=state["creator_id"],
                video_id=state["video_id"],
                trace_id=state["trace_id"],
            )
        )
        if output.category != "video_processing_stalled" or not 1 <= output.priority <= 5:
            raise ModelOutputValidationError("分诊模型输出不符合视频处理卡住场景合同")
        return {
            "triage": {
                "category": output.category,
                "priority": output.priority,
                "rationale": output.rationale[:500],
                "source": "structured-model",
            },
            "steps": _steps(state, "triage"),
        }

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
            raise ResolutionNotApplicableError(
                "non_processing_status",
                f"当前 P3 只为 PROCESSING 卡住场景生成恢复提案，实际为 {processing_status!r}",
            )
        if not evidence[0]["data"].get("lease_expire_at"):
            raise ResolutionNotApplicableError(
                "missing_lease_evidence",
                "PROCESSING 任务缺少租约到期时间，不能生成受控恢复提案",
            )
        suggestion: dict[str, Any] = {"action": SW_VIDEO_RECOVERY_ACTION, "source": "deterministic"}
        if model is not None:
            output = await model.resolve(
                ResolutionModelInput(
                    ticket_id=state["ticket_id"],
                    creator_id=state["creator_id"],
                    video_id=state["video_id"],
                    trace_id=state["trace_id"],
                    processing_status=processing_status,
                    lease_expire_at=evidence[0]["data"].get("lease_expire_at"),
                )
            )
            if output.action != SW_VIDEO_RECOVERY_ACTION:
                raise ModelOutputValidationError("处置模型建议了不在当前场景白名单内的动作")
            suggestion = {
                "action": output.action,
                "rationale": output.rationale[:500],
                "source": "structured-model",
            }
        proposal = ActionProposal(
            id=str(uuid.uuid4()),
            ticket_id=state["ticket_id"],
            action=SW_VIDEO_RECOVERY_ACTION,
            params={
                "ticket_id": state["ticket_id"],
                "creator_id": state["creator_id"],
                "video_id": state["video_id"],
                "trace_id": state["trace_id"],
            },
            evidence_ids=[evidence[0]["id"]],
            risk="high",
            created_by="flowpilot-resolution-agent",
            created_at=utc_now_iso(),
        )
        return {
            "proposal": proposal.to_dict(),
            "resolution_suggestion": suggestion,
            "steps": _steps(state, "resolution"),
        }

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
