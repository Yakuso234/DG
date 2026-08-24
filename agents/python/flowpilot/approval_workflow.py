"""把持久化审批、LangGraph 恢复和受控执行串为唯一服务入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langgraph.types import Command

from flowpilot.domain.models import Approval, ExecutionRecord
from flowpilot.domain.rbac import Actor
from flowpilot.domain.status import TicketStatus
from flowpilot.observability import traced_operation


class ApprovalWorkflowRepository(Protocol):
    async def approve_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        decision: str,
        modified_params: dict[str, Any] | None = None,
        note: str = "",
    ) -> Approval: ...

    async def transition(self, actor: Actor, ticket_id: str, target: TicketStatus) -> Any: ...

    async def execute_proposal(self, actor: Actor, proposal_id: str) -> ExecutionRecord: ...


class ApprovalWorkflowMismatchError(RuntimeError):
    """审批记录与待恢复的图状态不匹配，禁止执行外部动作。"""


@dataclass(frozen=True)
class ApprovalWorkflowResult:
    approval: Approval
    graph_state: dict[str, Any]
    execution: ExecutionRecord | None
    ticket_target: TicketStatus


class ApprovalWorkflowService:
    """审批必须先落库，再恢复图，最后才允许 service 身份执行。"""

    def __init__(
        self,
        repo: ApprovalWorkflowRepository,
        graph: Any,
        *,
        service_actor: Actor,
        escalation_actor: Actor,
    ) -> None:
        self._repo = repo
        self._graph = graph
        self._service_actor = service_actor
        self._escalation_actor = escalation_actor

    @traced_operation("flowpilot.workflow.approval")
    async def decide(
        self,
        approver: Actor,
        proposal_id: str,
        decision: str,
        config: dict[str, Any],
        *,
        modified_params: dict[str, Any] | None = None,
        note: str = "",
    ) -> ApprovalWorkflowResult:
        approval = await self._repo.approve_proposal(approver, proposal_id, decision, modified_params, note)
        graph_state = await self._graph.ainvoke(Command(resume=approval.decision), config)
        proposal = graph_state.get("proposal")
        if not isinstance(proposal, dict) or proposal.get("id") != approval.proposal_id:
            raise ApprovalWorkflowMismatchError("审批提案与 LangGraph checkpoint 不匹配，已阻止执行")
        if graph_state.get("approval", {}).get("decision") != approval.decision:
            raise ApprovalWorkflowMismatchError("LangGraph 恢复决议与持久化审批不匹配，已阻止执行")

        if approval.decision == "denied":
            await self._repo.transition(self._escalation_actor, approval.ticket_id, TicketStatus.ESCALATED)
            return ApprovalWorkflowResult(approval, graph_state, None, TicketStatus.ESCALATED)

        await self._repo.transition(self._service_actor, approval.ticket_id, TicketStatus.EXECUTING)
        execution = await self._repo.execute_proposal(self._service_actor, approval.proposal_id)
        if execution.status == "succeeded":
            target = TicketStatus.RESOLVED
        elif execution.status == "unknown":
            target = TicketStatus.RECONCILING
        else:
            target = TicketStatus.FAILED
        await self._repo.transition(self._service_actor, approval.ticket_id, target)
        return ApprovalWorkflowResult(approval, graph_state, execution, target)
