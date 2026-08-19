from __future__ import annotations

from typing import Any

from flowpilot.domain.models import ActionProposal, Approval, Evidence, ExecutionRecord, utc_now_iso
from flowpilot.domain.rbac import Actor, Role
from flowpilot.domain.status import TicketStatus
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot
from flowpilot.workflow_runtime import open_workflow_runtime


class FakeRuntimeRepo:
    def __init__(self) -> None:
        self.proposal: ActionProposal | None = None
        self.calls: list[str] = []

    async def transition(self, _actor: Actor, _ticket_id: str, _target: TicketStatus) -> None:
        self.calls.append("transition")

    async def add_evidence(self, _actor: Actor, evidence: Evidence) -> Evidence:
        self.calls.append("evidence")
        return evidence

    async def create_proposal(self, _actor: Actor, proposal: ActionProposal) -> ActionProposal:
        self.calls.append("proposal")
        self.proposal = proposal
        return proposal

    async def approve_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        decision: str,
        modified_params: dict[str, Any] | None = None,
        note: str = "",
    ) -> Approval:
        self.calls.append("approval")
        assert self.proposal is not None and self.proposal.id == proposal_id
        return Approval(
            "approval-1",
            proposal_id,
            self.proposal.ticket_id,
            actor.id,
            decision,
            modified_params,
            note,
            utc_now_iso(),
            1,
        )

    async def execute_proposal(self, _actor: Actor, proposal_id: str) -> ExecutionRecord:
        self.calls.append("execution")
        assert self.proposal is not None
        return ExecutionRecord(
            "execution-1",
            proposal_id,
            self.proposal.ticket_id,
            f"{proposal_id}:{self.proposal.action}",
            "succeeded",
            1,
            {"ok": True},
            utc_now_iso(),
            utc_now_iso(),
        )


async def test_runtime_shares_persistent_graph_between_start_and_approval(tmp_path) -> None:
    gateway = MockSwVideoOpsGateway(
        [VideoProcessingSnapshot(7, 9, "PROCESSING", "PROCESSING", 1, None, None, "2026-08-19 09:00:00", "seed")]
    )
    repo = FakeRuntimeRepo()
    checkpoint_path = str(tmp_path / "workflow-runtime.sqlite")
    async with open_workflow_runtime(
        repo,
        gateway,
        checkpoint_path=checkpoint_path,
        handler_actor=Actor("flowpilot-handler", Role.HANDLER),
        service_actor=Actor("flowpilot-executor", Role.SERVICE),
    ) as runtime:
        started = await runtime.ticket_workflow.start(
            ticket_id="ticket-1",
            creator_id=7,
            video_id=9,
            trace_id="trace-runtime",
            thread_id="thread-runtime",
        )
        completed = await runtime.approval_workflow.decide(
            Actor("u-approver", Role.APPROVER),
            started.proposal.id,
            "approved",
            {"configurable": {"thread_id": started.thread_id}},
        )

    assert completed.ticket_target is TicketStatus.RESOLVED
    assert completed.execution is not None and completed.execution.status == "succeeded"
    assert repo.calls == [
        "transition",
        "transition",
        "evidence",
        "proposal",
        "transition",
        "transition",
        "approval",
        "transition",
        "execution",
        "transition",
    ]
