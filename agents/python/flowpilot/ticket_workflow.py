"""启动工单 Agent 图，并把暂停前产物持久化到确定性工单域。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from flowpilot.agent_graph import initial_state
from flowpilot.domain.models import ActionProposal, AgentRun, Evidence, Ticket, utc_now_iso
from flowpilot.domain.rbac import Actor
from flowpilot.domain.status import TicketStatus
from flowpilot.observability import traced_operation


class TicketWorkflowRepository(Protocol):
    async def get_ticket(self, actor: Actor, ticket_id: str) -> Ticket: ...

    async def transition(self, actor: Actor, ticket_id: str, target: TicketStatus) -> Any: ...

    async def add_evidence(self, actor: Actor, evidence: Evidence) -> Evidence: ...

    async def create_proposal(self, actor: Actor, proposal: ActionProposal) -> ActionProposal: ...

    async def record_agent_run(self, actor: Actor, run: AgentRun) -> AgentRun: ...


class TicketWorkflowStateError(RuntimeError):
    """图未在审批点返回完整且属于当前工单的领域产物。"""


@dataclass(frozen=True)
class TicketWorkflowStartResult:
    ticket_id: str
    thread_id: str
    evidence: tuple[Evidence, ...]
    proposal: ActionProposal
    graph_state: dict[str, Any]
    agent_run: AgentRun
    ticket_target: TicketStatus = TicketStatus.WAITING_APPROVAL


class TicketWorkflowService:
    """以 handler 身份推进调查，并在人工审批前停止。"""

    def __init__(self, repo: TicketWorkflowRepository, graph: Any, *, handler_actor: Actor, model_label: str) -> None:
        self._repo = repo
        self._graph = graph
        self._handler_actor = handler_actor
        self._model_label = model_label

    @traced_operation("flowpilot.workflow.start")
    async def start(
        self,
        *,
        ticket_id: str,
        creator_id: int,
        video_id: int,
        trace_id: str,
        thread_id: str,
    ) -> TicketWorkflowStartResult:
        ticket = await self._repo.get_ticket(self._handler_actor, ticket_id)
        current = ticket.status
        if current is TicketStatus.NEW:
            await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.TRIAGED)
            current = TicketStatus.TRIAGED
        if current is TicketStatus.TRIAGED:
            await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.INVESTIGATING)
            current = TicketStatus.INVESTIGATING
        resumable = {TicketStatus.INVESTIGATING, TicketStatus.PROPOSED, TicketStatus.WAITING_APPROVAL}
        if current not in resumable:
            raise TicketWorkflowStateError(f"工单处于 {current.value}，不能启动或恢复调查工作流")

        config = {"configurable": {"thread_id": thread_id}}
        started_at = time.perf_counter()
        graph_state = await self._paused_or_new_state(
            ticket_id=ticket_id,
            creator_id=creator_id,
            video_id=video_id,
            trace_id=trace_id,
            config=config,
        )
        evidence_items, proposal = self._validated_outputs(graph_state, ticket_id)

        for evidence in evidence_items:
            await self._repo.add_evidence(self._handler_actor, evidence)
        await self._repo.create_proposal(self._handler_actor, proposal)
        if current is TicketStatus.INVESTIGATING:
            await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.PROPOSED)
            current = TicketStatus.PROPOSED
        if current is TicketStatus.PROPOSED:
            await self._repo.transition(self._handler_actor, ticket_id, TicketStatus.WAITING_APPROVAL)
        model_calls = graph_state.get("model_calls", [])
        tokens = self._summarize_tokens(model_calls)
        run = await self._repo.record_agent_run(
            self._handler_actor,
            AgentRun(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"flowpilot-run:{ticket_id}:{thread_id}:{trace_id}")),
                ticket_id=ticket_id,
                agent="flowpilot-main-graph",
                input_summary=f"creator_id={creator_id}, video_id={video_id}",
                output={
                    # 工作台需要用 thread_id 找回同一张图的 checkpoint；它是受限
                    # 业务标识，不保存 Prompt、Evidence 正文或模型理由。
                    "thread_id": thread_id,
                    "steps": graph_state.get("steps", []),
                    "proposal_id": proposal.id,
                    "proposal_action": proposal.action,
                    "risk": proposal.risk,
                    "evidence_count": len(evidence_items),
                    "model_calls": len(model_calls),
                    "model_latency_ms": sum(
                        item["latency_ms"] for item in model_calls if isinstance(item.get("latency_ms"), int)
                    ),
                },
                model=self._model_label,
                tokens=tokens,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                trace_id=trace_id,
                created_at=utc_now_iso(),
            ),
        )
        return TicketWorkflowStartResult(ticket_id, thread_id, tuple(evidence_items), proposal, graph_state, run)

    @staticmethod
    def _summarize_tokens(model_calls: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not model_calls:
            return None
        fields = ("input_tokens", "output_tokens", "total_tokens")
        if not all(isinstance(item.get(field), int) for item in model_calls for field in fields):
            return None
        return {
            "input_tokens": sum(item["input_tokens"] for item in model_calls),
            "output_tokens": sum(item["output_tokens"] for item in model_calls),
            "total_tokens": sum(item["total_tokens"] for item in model_calls),
            "calls": len(model_calls),
        }

    async def _paused_or_new_state(
        self,
        *,
        ticket_id: str,
        creator_id: int,
        video_id: int,
        trace_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = await self._graph.aget_state(config)
        values = dict(snapshot.values)
        if values.get("proposal") and values.get("evidence"):
            if any(getattr(task, "interrupts", ()) for task in snapshot.tasks):
                values["__interrupt__"] = True
                return values
            raise TicketWorkflowStateError("checkpoint 已越过审批暂停点，不能再次启动")
        return await self._graph.ainvoke(
            initial_state(
                ticket_id=ticket_id,
                creator_id=creator_id,
                video_id=video_id,
                trace_id=trace_id,
            ),
            config,
        )

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
