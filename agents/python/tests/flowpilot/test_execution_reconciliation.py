from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from flowpilot.action_runner import ActionOutcomeUnknownError, ReconciliationOutcome
from flowpilot.api import build_app
from flowpilot.db import TicketRepo
from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.domain.rbac import Actor, Role
from flowpilot.domain.status import TicketStatus
from flowpilot.execution_reconciliation import ExecutionReconciliationService


class FaultingRecoveryRunner:
    def __init__(self, outcome: ReconciliationOutcome) -> None:
        self.outcome = outcome
        self.run_keys: list[str] = []
        self.reconcile_keys: list[str] = []

    async def run(self, _proposal: ActionProposal, *, idempotency_key: str) -> dict:
        self.run_keys.append(idempotency_key)
        raise ActionOutcomeUnknownError("模拟 SW 已接受但响应在 DG 落库前丢失", result={"adapter": "fault-injection"})

    async def reconcile(self, _proposal: ActionProposal, *, idempotency_key: str) -> ReconciliationOutcome:
        self.reconcile_keys.append(idempotency_key)
        return self.outcome


async def _prepared(repo: TicketRepo) -> tuple[ActionProposal, str]:
    ticket = await repo.create_ticket(Actor("submitter", Role.SUBMITTER), "过期 lease 恢复", "测试未知结果")
    proposal = ActionProposal(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        action=SW_VIDEO_RECOVERY_ACTION,
        params={"ticket_id": ticket.id, "creator_id": 7, "video_id": 901, "trace_id": "trace-reconcile"},
        evidence_ids=[str(uuid.uuid4())],
        risk="high",
        created_by="handler",
        created_at=utc_now_iso(),
    )
    await repo.create_proposal(Actor("handler", Role.HANDLER), proposal)
    for target in (
        TicketStatus.TRIAGED,
        TicketStatus.INVESTIGATING,
        TicketStatus.PROPOSED,
        TicketStatus.WAITING_APPROVAL,
    ):
        await repo.transition(Actor("handler", Role.HANDLER), ticket.id, target)
    await repo.approve_proposal(Actor("approver", Role.APPROVER), proposal.id, "approved")
    await repo.transition(Actor("executor", Role.SERVICE), ticket.id, TicketStatus.EXECUTING)
    return proposal, ticket.id


async def test_unknown_result_reconciles_to_success_without_second_business_execution(postgres_pool, clean_db) -> None:
    runner = FaultingRecoveryRunner(ReconciliationOutcome("succeeded", {"ok": True, "recovery_id": "r-1"}))
    repo = TicketRepo(postgres_pool, runner)
    proposal, ticket_id = await _prepared(repo)

    first = await repo.execute_proposal(Actor("executor", Role.SERVICE), proposal.id)
    assert first.status == "unknown"
    assert first.attempts == 1
    assert first.reconcile_attempts == 0

    service = ExecutionReconciliationService(repo, runner)
    settled = await service.reconcile(first.id)

    assert settled.status == "succeeded"
    assert settled.attempts == 1
    assert settled.reconcile_attempts == 1
    assert runner.run_keys == runner.reconcile_keys
    assert (await repo.get_ticket(Actor("admin", Role.ADMIN), ticket_id)).status is TicketStatus.RESOLVED
    assert (await repo.get_proposal(Actor("admin", Role.ADMIN), proposal.id)).status == "executed"
    audit = await repo.audit_for(Actor("admin", Role.ADMIN), "execution", first.id)
    assert [event.action for event in audit] == [
        "execution.started",
        "execution.unknown",
        "execution.reconciled_succeeded",
    ]


async def test_unknown_result_stays_reconciling_then_escalates_after_budget(postgres_pool, clean_db) -> None:
    runner = FaultingRecoveryRunner(ReconciliationOutcome("unknown", {"ok": False, "detail": "SW unavailable"}))
    repo = TicketRepo(postgres_pool, runner)
    proposal, ticket_id = await _prepared(repo)
    record = await repo.execute_proposal(Actor("executor", Role.SERVICE), proposal.id)
    service = ExecutionReconciliationService(repo, runner, max_attempts=2)

    pending = await service.reconcile(record.id)
    assert pending.status == "unknown"
    assert pending.reconcile_attempts == 1
    assert pending.next_reconcile_at is not None
    assert (await repo.get_ticket(Actor("admin", Role.ADMIN), ticket_id)).status is TicketStatus.RECONCILING

    escalated = await service.reconcile(record.id)
    assert escalated.status == "escalated"
    assert escalated.reconcile_attempts == 2
    assert (await repo.get_ticket(Actor("admin", Role.ADMIN), ticket_id)).status is TicketStatus.ESCALATED


async def test_rejected_receipt_becomes_explicit_failed_ticket(postgres_pool, clean_db) -> None:
    runner = FaultingRecoveryRunner(ReconciliationOutcome("failed", {"ok": False, "reason": "PRECONDITION_NOT_MET"}))
    repo = TicketRepo(postgres_pool, runner)
    proposal, ticket_id = await _prepared(repo)
    record = await repo.execute_proposal(Actor("executor", Role.SERVICE), proposal.id)

    settled = await ExecutionReconciliationService(repo, runner).reconcile(record.id)

    assert settled.status == "failed"
    assert (await repo.get_ticket(Actor("admin", Role.ADMIN), ticket_id)).status is TicketStatus.FAILED


async def test_run_once_claims_due_unknown_record(postgres_pool, clean_db) -> None:
    runner = FaultingRecoveryRunner(ReconciliationOutcome("succeeded", {"ok": True, "recovery_id": "r-batch"}))
    repo = TicketRepo(postgres_pool, runner)
    proposal, ticket_id = await _prepared(repo)
    record = await repo.execute_proposal(Actor("executor", Role.SERVICE), proposal.id)

    settled = await ExecutionReconciliationService(repo, runner).run_once()

    assert [item.id for item in settled] == [record.id]
    assert settled[0].status == "succeeded"
    assert (await repo.get_ticket(Actor("admin", Role.ADMIN), ticket_id)).status is TicketStatus.RESOLVED


async def test_execution_read_and_manual_reconcile_api_require_allowed_roles(postgres_pool, clean_db) -> None:
    runner = FaultingRecoveryRunner(ReconciliationOutcome("succeeded", {"ok": True}))
    repo = TicketRepo(postgres_pool, runner)
    proposal, ticket_id = await _prepared(repo)
    record = await repo.execute_proposal(Actor("executor", Role.SERVICE), proposal.id)
    app = build_app(postgres_pool, runner)
    transport = ASGITransport(app=app)
    admin = {"x-user-id": "admin", "x-user-role": "admin"}
    submitter = {"x-user-id": "submitter", "x-user-role": "submitter"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get(f"/api/tickets/{ticket_id}/executions", headers=admin)
        denied = await client.post(f"/api/executions/{record.id}/reconcile", headers=submitter)
        settled = await client.post(f"/api/executions/{record.id}/reconcile", headers=admin)

    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "unknown"
    assert denied.status_code == 403
    assert settled.status_code == 200
    assert settled.json()["status"] == "succeeded"
