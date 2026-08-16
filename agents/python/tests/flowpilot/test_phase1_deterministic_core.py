"""Phase 1 验收测试：确定性工单闭环（无 LLM）。

覆盖路线图 Phase 1 测试要求：
- 所有非法状态转移
- 并发审批的版本冲突 / 乐观锁冲突
- 相同幂等键重复调用
- 越权访问和越权动作
- 审计记录一致性
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from flowpilot.db import ApprovalConflictError, NotFoundError, TicketRepo, VersionConflictError
from flowpilot.domain.executor import (
    ApprovalRequiredError,
    ParamValidationError,
    validate_params,
)
from flowpilot.domain.models import ActionProposal, Evidence, utc_now_iso
from flowpilot.domain.rbac import Actor, PermissionDeniedError, Role
from flowpilot.domain.status import IllegalTransitionError, LEGAL_TRANSITIONS, TicketStatus

# ─────────────────────── 领域级（无 DB）───────────────────────


def test_all_illegal_transitions_rejected() -> None:
    from flowpilot.domain.status import assert_legal_transition

    for current, legal_targets in LEGAL_TRANSITIONS.items():
        for target in TicketStatus:
            if target in legal_targets:
                assert_legal_transition(current, target)  # 合法转移不抛
            else:
                with pytest.raises(IllegalTransitionError):
                    assert_legal_transition(current, target)
    # 代表性断言
    with pytest.raises(IllegalTransitionError):
        assert_legal_transition(TicketStatus.NEW, TicketStatus.RESOLVED)
    with pytest.raises(IllegalTransitionError):
        assert_legal_transition(TicketStatus.RESOLVED, TicketStatus.PROPOSED)


def test_param_contract_rejects_unknown_action_and_missing_params() -> None:
    with pytest.raises(ParamValidationError):
        validate_params("drop_table", {"ticket_id": "T-1"})
    with pytest.raises(ParamValidationError):
        validate_params("restart_pipeline", {})
    with pytest.raises(ParamValidationError):
        validate_params("restart_pipeline", {"ticket_id": "T-1", "evil": True})


def test_rbac_denies_out_of_role_actions() -> None:
    submitter = Actor(id="u1", role=Role.SUBMITTER)
    with pytest.raises(PermissionDeniedError):
        submitter.check("ticket.transition")
    approver = Actor(id="u2", role=Role.APPROVER)
    with pytest.raises(PermissionDeniedError):
        approver.check("execution.run")


# ─────────────────────── 集成级（testcontainers Postgres）───────────────────────


@pytest.fixture
def repo(postgres_pool, clean_db):
    return TicketRepo(postgres_pool)


def _actor(role: Role, uid: str = "u-test") -> Actor:
    return Actor(id=uid, role=role)


def _proposal(ticket_id: str, action: str, risk: str) -> ActionProposal:
    params: dict[str, str] = {"ticket_id": ticket_id}
    if action == "add_note":
        params["content"] = "auto note"
    return ActionProposal(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        action=action,
        params=params,
        evidence_ids=[],
        risk=risk,
        created_by="u-handler",
        created_at=utc_now_iso(),
    )


async def test_deterministic_closed_loop_without_llm(repo: TicketRepo) -> None:
    """建单 → 分诊 → 调查（证据）→ 提案 → 审批 → 执行 → RESOLVED，全程无 LLM。"""
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER, "u-sub"), "视频处理中", "上传后长时间处理中")
    assert ticket.status is TicketStatus.NEW

    handler = _actor(Role.HANDLER, "u-handler")
    ticket = await repo.transition(handler, ticket.id, TicketStatus.TRIAGED)
    ticket = await repo.transition(handler, ticket.id, TicketStatus.INVESTIGATING)
    assert ticket.version == 2  # 两次转移各 +1

    evidence = Evidence(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        tool="get_ticket_status",
        source="mock-business-mcp",
        data={"state": "processing", "elapsed_min": 90},
        collected_at=utc_now_iso(),
    )
    await repo.add_evidence(handler, evidence)
    items = await repo.list_evidence(handler, ticket.id)
    assert len(items) == 1 and items[0].source == "mock-business-mcp"

    proposal = _proposal(ticket.id, "restart_pipeline", "high")
    await repo.create_proposal(handler, proposal)
    ticket = await repo.transition(handler, ticket.id, TicketStatus.PROPOSED)
    ticket = await repo.transition(handler, ticket.id, TicketStatus.WAITING_APPROVAL)

    approver = _actor(Role.APPROVER, "u-approver")
    approval = await repo.approve_proposal(approver, proposal.id, "approved", note="已确认重启安全")
    assert approval.decision == "approved"

    service = _actor(Role.SERVICE, "svc-executor")
    ticket = await repo.transition(service, ticket.id, TicketStatus.EXECUTING)
    record = await repo.execute_proposal(service, proposal.id)
    assert record.status == "succeeded"
    ticket = await repo.transition(service, ticket.id, TicketStatus.RESOLVED)
    assert ticket.status is TicketStatus.RESOLVED


async def test_high_risk_proposal_cannot_execute_without_approval(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER), "高危", "需要高危动作")
    handler = _actor(Role.HANDLER)
    await repo.transition(handler, ticket.id, TicketStatus.TRIAGED)
    await repo.transition(handler, ticket.id, TicketStatus.INVESTIGATING)
    proposal = _proposal(ticket.id, "delete_data", "high")
    await repo.create_proposal(handler, proposal)
    await repo.transition(handler, ticket.id, TicketStatus.PROPOSED)
    await repo.transition(handler, ticket.id, TicketStatus.WAITING_APPROVAL)
    service = _actor(Role.SERVICE)
    with pytest.raises(ApprovalRequiredError):
        await repo.execute_proposal(service, proposal.id)


async def test_idempotent_execution_same_key(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER), "幂等", "x")
    handler = _actor(Role.HANDLER)
    proposal = _proposal(ticket.id, "add_note", "low")
    await repo.create_proposal(handler, proposal)
    service = _actor(Role.SERVICE)
    first = await repo.execute_proposal(service, proposal.id)
    second = await repo.execute_proposal(service, proposal.id)
    assert first.id == second.id
    assert first.idempotency_key == second.idempotency_key == f"{proposal.id}:add_note"


async def test_approval_concurrent_decision_rejected(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER), "并发审批", "x")
    handler = _actor(Role.HANDLER)
    proposal = _proposal(ticket.id, "restart_pipeline", "high")
    await repo.create_proposal(handler, proposal)
    a1, a2 = _actor(Role.APPROVER, "u-a1"), _actor(Role.APPROVER, "u-a2")
    first = await repo.approve_proposal(a1, proposal.id, "approved")
    assert first.version == 1
    with pytest.raises(ApprovalConflictError):
        await repo.approve_proposal(a2, proposal.id, "denied")


async def test_version_conflict_on_concurrent_transition(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER), "乐观锁", "x")
    handler = _actor(Role.HANDLER)
    # 两个并发转移竞争同一个合法目标（NEW -> TRIAGED）：
    # 行锁串行化后，第二个转移读到 TRIAGED 状态，再转 TRIAGED 非法；
    # 若读旧版本则 UPDATE WHERE version 不匹配，同样被拒。
    t1 = asyncio.create_task(repo.transition(handler, ticket.id, TicketStatus.TRIAGED))
    t2 = asyncio.create_task(repo.transition(handler, ticket.id, TicketStatus.TRIAGED))
    results = await asyncio.gather(t1, t2, return_exceptions=True)
    succeeded = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(succeeded) == 1
    assert len(failed) == 1
    assert isinstance(failed[0], (VersionConflictError, IllegalTransitionError))


async def test_unauthorized_transition_rejected(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER, "u-sub"), "越权", "x")
    with pytest.raises(PermissionDeniedError):
        await repo.transition(_actor(Role.SUBMITTER, "u-sub"), ticket.id, TicketStatus.TRIAGED)
    # 服务身份也不能直接调查
    with pytest.raises(PermissionError):
        await repo.transition(_actor(Role.SERVICE), ticket.id, TicketStatus.INVESTIGATING)


async def test_audit_trail_covers_every_write(repo: TicketRepo) -> None:
    ticket = await repo.create_ticket(_actor(Role.SUBMITTER, "u-sub"), "审计", "x")
    handler = _actor(Role.HANDLER, "u-handler")
    await repo.transition(handler, ticket.id, TicketStatus.TRIAGED)
    evidence = Evidence(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        tool="get_ticket_status",
        source="mock-business-mcp",
        data={},
        collected_at=utc_now_iso(),
    )
    await repo.add_evidence(handler, evidence)
    proposal = _proposal(ticket.id, "add_note", "low")
    await repo.create_proposal(handler, proposal)
    admin = _actor(Role.ADMIN, "u-admin")
    events = await repo.audit_for(admin, "ticket", ticket.id)
    actions = {e.action for e in events}
    assert {"ticket.create", "ticket.transition"} <= actions
    ev_events = await repo.audit_for(admin, "evidence", evidence.id)
    assert ev_events and ev_events[0].action == "evidence.create"


async def test_get_missing_ticket_raises_not_found(repo: TicketRepo) -> None:
    with pytest.raises(NotFoundError):
        await repo.get_ticket(_actor(Role.HANDLER), str(uuid.uuid4()))
