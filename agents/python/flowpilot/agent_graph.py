"""P3 单 LangGraph 主图：分诊、调查、提案与风险复核。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION, risk_of, validate_params
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.observability import traced_agent_step
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
    ticket_title: str
    ticket_description: str
    triage: dict[str, Any]
    resolution_suggestion: dict[str, Any]
    diagnosis: dict[str, Any]
    evidence: list[dict[str, Any]]
    proposal: dict[str, Any]
    risk_review: dict[str, Any]
    approval: dict[str, Any]
    model_calls: list[dict[str, Any]]
    steps: list[str]


def initial_state(
    *,
    ticket_id: str,
    creator_id: int,
    video_id: int,
    trace_id: str,
    ticket_title: str = "",
    ticket_description: str = "",
) -> FlowPilotGraphState:
    return {
        "ticket_id": ticket_id,
        "creator_id": creator_id,
        "video_id": video_id,
        "trace_id": trace_id,
        "ticket_title": ticket_title[:500],
        "ticket_description": ticket_description[:2000],
        "steps": [],
    }


def _steps(state: FlowPilotGraphState, step: str) -> list[str]:
    return [*state.get("steps", []), step]


def _lease_is_expired(raw: Any, *, now: datetime) -> bool | None:
    """返回租约是否已过期；None 代表格式不可信，必须失败关闭。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed < now.astimezone(UTC)


def build_graph(
    gateway: SwVideoOpsGateway,
    *,
    checkpointer: Any = None,
    require_approval: bool = False,
    model: StructuredFlowPilotModel | None = None,
    now: datetime | None = None,
):
    """构建主图；可选模型只提供受控建议，领域校验不交给模型。"""

    @traced_agent_step("triage")
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
                ticket_title=state.get("ticket_title", ""),
                ticket_description=state.get("ticket_description", ""),
            )
        )
        if output.category != "video_processing_stalled" or not 1 <= output.priority <= 5:
            raise ModelOutputValidationError("分诊模型输出不符合视频处理卡住场景合同")
        result: dict[str, Any] = {
            "triage": {
                "category": output.category,
                "priority": output.priority,
                "rationale": output.rationale[:500],
                "source": "structured-model",
            },
            "steps": _steps(state, "triage"),
        }
        if output.metrics is not None:
            result["model_calls"] = [*state.get("model_calls", []), output.metrics.to_dict()]
        return result

    @traced_agent_step("investigation")
    async def investigate(state: FlowPilotGraphState) -> dict[str, Any]:
        snapshot = await gateway.get_video_processing_status(
            creator_id=state["creator_id"], video_id=state["video_id"], trace_id=state["trace_id"]
        )
        evidence = status_to_evidence(ticket_id=state["ticket_id"], snapshot=snapshot)
        return {"evidence": [evidence.to_dict()], "steps": _steps(state, "investigation")}

    @traced_agent_step("resolution")
    async def resolution(state: FlowPilotGraphState) -> dict[str, Any]:
        evidence = state["evidence"]
        data = evidence[0]["data"]
        processing_status = data["processing_status"]
        base = {"evidence_ids": [evidence[0]["id"]], "source": "deterministic"}
        if processing_status != "PROCESSING":
            return {
                "diagnosis": {**base, "decision": "escalate", "reason": "non_processing_status"},
                "resolution_suggestion": {"decision": "escalate", "source": "deterministic"},
                "steps": _steps(state, "resolution"),
            }
        lease_raw = data.get("lease_expire_at")
        lease_state = _lease_is_expired(lease_raw, now=now or datetime.now(UTC))
        if lease_state is None:
            reason = (
                "missing_lease_evidence"
                if not isinstance(lease_raw, str) or not lease_raw.strip()
                else "invalid_lease_evidence"
            )
            return {
                "diagnosis": {**base, "decision": "escalate", "reason": reason},
                "resolution_suggestion": {"decision": "escalate", "source": "deterministic"},
                "steps": _steps(state, "resolution"),
            }
        if not lease_state:
            return {
                "diagnosis": {**base, "decision": "wait", "reason": "lease_not_expired"},
                "resolution_suggestion": {"decision": "wait", "source": "deterministic"},
                "steps": _steps(state, "resolution"),
            }

        suggestion: dict[str, Any] = {"decision": "recover", "source": "deterministic"}
        diagnosis: dict[str, Any] = {**base, "decision": "recover", "reason": "expired_lease_confirmed"}
        if model is not None:
            output = await model.resolve(
                ResolutionModelInput(
                    ticket_id=state["ticket_id"],
                    creator_id=state["creator_id"],
                    video_id=state["video_id"],
                    trace_id=state["trace_id"],
                    ticket_title=state.get("ticket_title", ""),
                    ticket_description=state.get("ticket_description", ""),
                    processing_status=processing_status,
                    lease_expire_at=data.get("lease_expire_at"),
                    retry_count=data.get("retry_count"),
                    error_summary=data.get("error_summary"),
                )
            )
            suggestion = {
                "decision": output.decision,
                "rationale": output.rationale[:500],
                "source": "structured-model",
            }
            diagnosis = {
                **base,
                "decision": output.decision,
                "reason": f"model_{output.decision}",
                "source": "structured-model",
            }
            if output.decision != "recover":
                result: dict[str, Any] = {
                    "diagnosis": diagnosis,
                    "resolution_suggestion": suggestion,
                    "steps": _steps(state, "resolution"),
                }
                if output.metrics is not None:
                    result["model_calls"] = [*state.get("model_calls", []), output.metrics.to_dict()]
                return result
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
        result = {
            "proposal": proposal.to_dict(),
            "resolution_suggestion": suggestion,
            "diagnosis": diagnosis,
            "steps": _steps(state, "resolution"),
        }
        if model is not None and output.metrics is not None:
            result["model_calls"] = [*state.get("model_calls", []), output.metrics.to_dict()]
        return result

    @traced_agent_step("risk_review")
    async def risk_review(state: FlowPilotGraphState) -> dict[str, Any]:
        proposal = ActionProposal.from_dict(state["proposal"])
        validate_params(proposal.action, proposal.params)
        risk = risk_of(proposal.action).value
        return {
            "risk_review": {"approved_for_human_review": True, "authoritative_risk": risk},
            "steps": _steps(state, "risk_review"),
        }

    @traced_agent_step("escalation")
    async def escalation(state: FlowPilotGraphState) -> dict[str, Any]:
        return {"steps": _steps(state, "escalation")}

    def route_after_resolution(state: FlowPilotGraphState) -> str:
        return "risk_review" if isinstance(state.get("proposal"), dict) else "escalation"

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
    builder.add_node("escalation", escalation)
    if require_approval:
        builder.add_node("await_approval", await_approval)
    builder.add_edge(START, "triage")
    builder.add_edge("triage", "investigation")
    builder.add_edge("investigation", "resolution")
    builder.add_conditional_edges(
        "resolution",
        route_after_resolution,
        {"risk_review": "risk_review", "escalation": "escalation"},
    )
    builder.add_edge("escalation", END)
    if require_approval:
        builder.add_edge("risk_review", "await_approval")
        builder.add_edge("await_approval", END)
    else:
        builder.add_edge("risk_review", END)
    return builder.compile(checkpointer=checkpointer)
