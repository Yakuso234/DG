"""启动工单 Agent 图，并把暂停前产物持久化到确定性工单域。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from flowpilot.agent_graph import initial_state
from flowpilot.domain.models import ActionProposal, Evidence
from flowpilot.domain.rbac import Actor
from flowpilot.domain.status import TicketStatus


class TicketWorkflowRepository(Protocol):
    async def transition(self, actor: Actor, ticket_id: str, target: TicketStatus) -> Any: ...

    async def add_evidence(self, actor: Actor, evidence: Evidence) -> Evidence: ...

    async def create_proposal(self, actor: Actor, proposal: ActionProposal) -> ActionProposal: ...


class TicketWorkflowStateError(RuntimeError):
    """图未在审批点返回完整且属于当前工单的领域产物。"""


@dataclass(frozen=True)
class TicketWorkflowStartResult:
    ticket_id: str
    thread_id: str
    evidence: tuple[Evidence, ...]
    proposal: ActionProposal
    graph_state: dict[str, Any]
    ticket_target: TicketStatus = TicketStatus.WAITING_APPROVAL


class TicketWorkflowService:
    """以 handler 身份推进调查，并在人工审批前停止。"""

    def __init__(self, repo: TicketWorkflowRepository, graph: Any, *, handler_actor: Actor) -> None:
        self._repo = repo
        self._graph = graph
        self._handler_actor = handler_actor

    async def start(
        self,
        *,
        ticket_id: str,
        creator_id: int,
        video_id: int,
        trace_id: str,
        thread_id: str,
    ) -> TicketWorkflowStartResult:
        await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.TRIAGED)
        await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.INVESTIGATING)

        config = {"configurable": {"thread_id": thread_id}}
        graph_state = await self._graph.ainvoke(
            initial_state(
                ticket_id=ticket_id,
                creator_id=creator_id,
                video_id=video_id,
                trace_id=trace_id,
            ),
            config,
        )
        evidence_items, proposal = self._validated_outputs(graph_state, ticket_id)

        for evidence in evidence_items:
            await self._repo.add_evidence(self._handler_actor, evidence)
        await self._repo.create_proposal(self._handler_actor, proposal)
        await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.PROPOSED)
        await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.WAITING_APPROVAL)
        return TicketWorkflowStartResult(ticket_id, thread_id, tuple(evidence_items), proposal, graph_state)

    @staticmethod
    def _validated_outputs(graph_state: dict[str, Any], ticket_id: str) -> tuple[list[Evidence], ActionProposal]:
        if "__interrupt__" not in graph_state:
            raise TicketWorkflowStateError("Agent 图未暂停在人工审批点")
        raw_evidence = graph_state.get("evidence")
        raw_proposal = graph_state.get("proposal")
        if not isinstance(raw_evidence, list) or not raw_evidence or not isinstance(raw_proposal, dict):
            raise TicketWorkflowStateError("Agent 图缺少 Evidence 或 ActionProposal")
        try:
            evidence_items = [Evidence(**item) for item in raw_evidence if isinstance(item, dict)]
            proposal = ActionProposal.from_dict(raw_proposal)
        except (KeyError, TypeError) as exc:
            raise TicketWorkflowStateError("Agent 图产物不符合领域模型") from exc
        if len(evidence_items) != len(raw_evidence):
            raise TicketWorkflowStateError("Agent 图包含非结构化 Evidence")
        if proposal.ticket_id != ticket_id or any(item.ticket_id != ticket_id for item in evidence_items):
            raise TicketWorkflowStateError("Agent 图产物与当前工单不匹配")
        if set(proposal.evidence_ids) - {item.id for item in evidence_items}:
            raise TicketWorkflowStateError("ActionProposal 引用了不存在的 Evidence")
        return evidence_items, proposal
