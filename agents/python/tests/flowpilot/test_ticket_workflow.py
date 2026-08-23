from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from flowpilot.agent_graph import build_graph
from flowpilot.domain.models import ActionProposal, AgentRun, Evidence, Ticket
from flowpilot.domain.rbac import Actor, Role
from flowpilot.domain.status import TicketStatus
from flowpilot.structured_model import (
    FakeStructuredFlowPilotModel,
    ModelCallMetrics,
    ResolutionModelOutput,
    TriageModelOutput,
)
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot
from flowpilot.ticket_workflow import TicketWorkflowService


class FakeTicketWorkflowRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.status = TicketStatus.NEW
        self.runs: dict[str, AgentRun] = {}

    async def get_ticket(self, _actor: Actor, ticket_id: str) -> Ticket:
        return Ticket(ticket_id, "test", "", 3, status=self.status)

    async def transition(self, _actor: Actor, ticket_id: str, target: TicketStatus) -> None:
        self.calls.append(("transition", (ticket_id, target)))
        self.status = target

    async def add_evidence(self, _actor: Actor, evidence: Evidence) -> Evidence:
        self.calls.append(("evidence", evidence))
        return evidence

    async def create_proposal(self, _actor: Actor, proposal: ActionProposal) -> ActionProposal:
        self.calls.append(("proposal", proposal))
        return proposal

    async def record_agent_run(self, _actor: Actor, run: AgentRun) -> AgentRun:
        self.calls.append(("agent_run", run))
        return self.runs.setdefault(run.id, run)


async def test_start_workflow_persists_graph_outputs_before_waiting_for_approval() -> None:
    gateway = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-18 00:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    graph = build_graph(gateway, checkpointer=MemorySaver(), require_approval=True)
    repo = FakeTicketWorkflowRepo()
    service = TicketWorkflowService(
        repo,
        graph,
        handler_actor=Actor("flowpilot-handler", Role.HANDLER),
        model_label="deterministic",
    )

    result = await service.start(
        ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-start", thread_id="thread-start"
    )

    assert result.ticket_target is TicketStatus.WAITING_APPROVAL
    assert result.proposal.ticket_id == "ticket-1"
    assert result.proposal.evidence_ids == [result.evidence[0].id]
    assert [call[0] for call in repo.calls] == [
        "transition",
        "transition",
        "evidence",
        "proposal",
        "transition",
        "transition",
        "agent_run",
    ]
    assert repo.calls[0][1][1] is TicketStatus.TRIAGED
    assert repo.calls[1][1][1] is TicketStatus.INVESTIGATING
    assert repo.calls[-3][1][1] is TicketStatus.PROPOSED
    assert repo.calls[-2][1][1] is TicketStatus.WAITING_APPROVAL
    assert result.agent_run.model == "deterministic"
    assert result.agent_run.trace_id == "trace-start"
    assert result.agent_run.output["thread_id"] == "thread-start"

    first_call_count = len(repo.calls)
    repeated = await service.start(
        ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-start", thread_id="thread-start"
    )
    assert repeated.proposal.id == result.proposal.id
    assert repeated.agent_run.id == result.agent_run.id
    assert repeated.agent_run.latency_ms == result.agent_run.latency_ms
    assert not [call for call in repo.calls[first_call_count:] if call[0] == "transition"]


async def test_agent_run_summarizes_structured_model_tokens_and_latency() -> None:
    gateway = MockSwVideoOpsGateway(
        [VideoProcessingSnapshot(7, 9, "PROCESSING", "PROCESSING", 1, "expired", None, "now", "seed")]
    )
    model = FakeStructuredFlowPilotModel(
        triage_output=TriageModelOutput(
            "video_processing_stalled",
            4,
            "triage",
            ModelCallMetrics("triage", 10, 4, 14, 120),
        ),
        resolution_output=ResolutionModelOutput(
            "recover_expired_video_processing",
            "resolve",
            ModelCallMetrics("resolve", 12, 5, 17, 180),
        ),
    )
    graph = build_graph(gateway, checkpointer=MemorySaver(), require_approval=True, model=model)
    repo = FakeTicketWorkflowRepo()
    service = TicketWorkflowService(
        repo,
        graph,
        handler_actor=Actor("flowpilot-handler", Role.HANDLER),
        model_label="qwen-plus",
    )

    result = await service.start(
        ticket_id="ticket-usage", creator_id=7, video_id=9, trace_id="trace-usage", thread_id="thread-usage"
    )

    assert result.agent_run.tokens == {
        "input_tokens": 22,
        "output_tokens": 9,
        "total_tokens": 31,
        "calls": 2,
    }
    assert result.agent_run.output["model_calls"] == 2
    assert result.agent_run.output["model_latency_ms"] == 300
