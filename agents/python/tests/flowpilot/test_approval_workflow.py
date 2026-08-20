from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.approval_workflow import ApprovalWorkflowMismatchError, ApprovalWorkflowService
from flowpilot.domain.models import Approval, ExecutionRecord, utc_now_iso
from flowpilot.domain.rbac import Actor, Role
from flowpilot.domain.status import TicketStatus
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot


class FakeApprovalWorkflowRepo:
    def __init__(self, *, approval_proposal_id: str | None = None, execution_status: str = "succeeded") -> None:
        self.approval_proposal_id = approval_proposal_id
        self.execution_status = execution_status
        self.calls: list[tuple[str, Any]] = []

    async def approve_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        decision: str,
        _modified_params: dict[str, Any] | None = None,
        _note: str = "",
    ) -> Approval:
        self.calls.append(("approve", proposal_id))
        return Approval(
            id="approval-1",
            proposal_id=self.approval_proposal_id or proposal_id,
            ticket_id="ticket-1",
            approver=actor.id,
            decision=decision,
            modified_params=None,
            note="",
            decided_at=utc_now_iso(),
            version=1,
        )

    async def transition(self, _actor: Actor, ticket_id: str, target: TicketStatus) -> None:
        self.calls.append(("transition", (ticket_id, target)))

    async def execute_proposal(self, _actor: Actor, proposal_id: str) -> ExecutionRecord:
        self.calls.append(("execute", proposal_id))
        return ExecutionRecord(
            id="execution-1",
            proposal_id=proposal_id,
            ticket_id="ticket-1",
            idempotency_key=f"{proposal_id}:recover_expired_video_processing",
            status=self.execution_status,
            attempts=1,
            result={},
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
        )


async def _paused_graph() -> tuple[Any, dict[str, Any]]:
    gateway = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-18 00:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    graph = build_graph(gateway, checkpointer=MemorySaver(), require_approval=True)
    config = {"configurable": {"thread_id": "approval-service-thread"}}
    paused = await graph.ainvoke(
        initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-approval-service"), config
    )
    assert "__interrupt__" in paused
    return graph, config


def _service(repo: FakeApprovalWorkflowRepo, graph: Any) -> ApprovalWorkflowService:
    return ApprovalWorkflowService(
        repo,
        graph,
        service_actor=Actor("svc-executor", Role.SERVICE),
        escalation_actor=Actor("u-handler", Role.HANDLER),
    )


async def test_approved_checkpoint_resumes_then_executes_under_service_identity() -> None:
    graph, config = await _paused_graph()
    repo = FakeApprovalWorkflowRepo()

    result = await _service(repo, graph).decide(
        Actor("u-approver", Role.APPROVER),
        (await graph.aget_state(config)).values["proposal"]["id"],
        "approved",
        config,
    )

    assert result.ticket_target is TicketStatus.RESOLVED
    assert result.execution is not None and result.execution.status == "succeeded"
    assert [call[0] for call in repo.calls] == ["approve", "transition", "execute", "transition"]
    assert repo.calls[1][1][1] is TicketStatus.EXECUTING
    assert repo.calls[-1][1][1] is TicketStatus.RESOLVED


async def test_denied_checkpoint_escalates_without_calling_executor() -> None:
    graph, config = await _paused_graph()
    repo = FakeApprovalWorkflowRepo()

    result = await _service(repo, graph).decide(
        Actor("u-approver", Role.APPROVER),
        (await graph.aget_state(config)).values["proposal"]["id"],
        "denied",
        config,
    )

    assert result.ticket_target is TicketStatus.ESCALATED
    assert result.execution is None
    assert [call[0] for call in repo.calls] == ["approve", "transition"]
    assert repo.calls[-1][1][1] is TicketStatus.ESCALATED


async def test_mismatched_checkpoint_never_calls_executor() -> None:
    graph, config = await _paused_graph()
    repo = FakeApprovalWorkflowRepo(approval_proposal_id="other-proposal")

    with pytest.raises(ApprovalWorkflowMismatchError):
        await _service(repo, graph).decide(Actor("u-approver", Role.APPROVER), "other-proposal", "approved", config)

    assert [call[0] for call in repo.calls] == ["approve"]
