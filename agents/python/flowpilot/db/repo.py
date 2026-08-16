"""asyncpg 数据访问：状态转移乐观锁、审批行锁、幂等执行与审计。

所有写操作在同一个连接/事务内完成业务变更 + 审计事件写入，保证
"业务写操作可追溯"的一致性（Phase 1 验收红线）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import asyncpg

from flowpilot.domain.executor import (
    ApprovalRequiredError,
    assert_executable,
    next_idempotency_key,
)
from flowpilot.domain.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Evidence,
    ExecutionRecord,
    Ticket,
    utc_now_iso,
)
from flowpilot.domain.rbac import Actor
from flowpilot.domain.status import IllegalTransitionError, TicketStatus


class NotFoundError(LookupError):
    pass


class VersionConflictError(RuntimeError):
    """乐观锁冲突：并发修改被拒绝。"""


class ApprovalConflictError(RuntimeError):
    """审批并发冲突：提案已被其他人决议。"""


def _row_to_ticket(row: asyncpg.Record) -> Ticket:
    return Ticket(
        id=str(row["id"]),
        title=row["title"],
        description=row["description"],
        priority=int(row["priority"]),
        status=TicketStatus(row["status"]),
        submitter=row["submitter"] or "",
        assignee=row["assignee"],
        version=int(row["version"]),
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


async def _audit(
    conn: asyncpg.Connection,
    actor: Actor,
    entity: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_events (entity, entity_id, action, actor, actor_role, before, after)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
        """,
        entity,
        entity_id,
        action,
        actor.id,
        actor.role.value,
        json.dumps(before, ensure_ascii=False) if before is not None else None,
        json.dumps(after, ensure_ascii=False) if after is not None else None,
    )


class TicketRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_ticket(self, actor: Actor, title: str, description: str, priority: int = 3) -> Ticket:
        actor.check("ticket.create")
        ticket_id = uuid.uuid4()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO tickets (id, title, description, priority, submitter)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                    """,
                    ticket_id,
                    title,
                    description,
                    priority,
                    actor.id,
                )
                await _audit(
                    conn,
                    actor,
                    "ticket",
                    str(ticket_id),
                    "ticket.create",
                    None,
                    {"title": title, "priority": priority, "status": "NEW"},
                )
        assert row is not None
        return _row_to_ticket(row)

    async def get_ticket(self, actor: Actor, ticket_id: str) -> Ticket:
        actor.check("ticket.view_any")
        row = await self._pool.fetchrow("SELECT * FROM tickets WHERE id = $1", uuid.UUID(ticket_id))
        if row is None:
            raise NotFoundError(f"工单 {ticket_id} 不存在")
        return _row_to_ticket(row)

    async def list_tickets(self, actor: Actor, limit: int = 50) -> list[Ticket]:
        actor.check("ticket.view_any")
        rows = await self._pool.fetch(
            "SELECT * FROM tickets ORDER BY created_at DESC LIMIT $1", min(limit, 200)
        )
        return [_row_to_ticket(r) for r in rows]

    async def transition(self, actor: Actor, ticket_id: str, target: TicketStatus) -> Ticket:
        """状态转移（乐观锁）：WHERE version 匹配失败即拒绝并发修改。"""
        from flowpilot.domain.rbac import can_transition_to
        from flowpilot.domain.status import assert_legal_transition

        actor.check("ticket.transition")
        if not can_transition_to(actor.role, target):
            raise PermissionError(f"{actor.role.value} 不能转移到 {target.value}")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM tickets WHERE id = $1 FOR UPDATE", uuid.UUID(ticket_id)
                )
                if row is None:
                    raise NotFoundError(f"工单 {ticket_id} 不存在")
                ticket = _row_to_ticket(row)
                assert_legal_transition(ticket.status, target)
                updated = await conn.fetchrow(
                    """
                    UPDATE tickets SET status = $2, version = version + 1, updated_at = NOW()
                    WHERE id = $1 AND version = $3
                    RETURNING *
                    """,
                    uuid.UUID(ticket_id),
                    target.value,
                    ticket.version,
                )
                if updated is None:
                    raise VersionConflictError(f"工单 {ticket_id} 版本冲突（期望 v{ticket.version}）")
                await _audit(
                    conn,
                    actor,
                    "ticket",
                    ticket_id,
                    "ticket.transition",
                    {"status": ticket.status.value, "version": ticket.version},
                    {"status": target.value, "version": ticket.version + 1},
                )
        assert updated is not None
        return _row_to_ticket(updated)

    async def add_evidence(self, actor: Actor, evidence: Evidence) -> Evidence:
        actor.check("evidence.create")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO evidence (id, ticket_id, tool, source, data, collected_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    """,
                    uuid.UUID(evidence.id),
                    uuid.UUID(evidence.ticket_id),
                    evidence.tool,
                    evidence.source,
                    json.dumps(evidence.data, ensure_ascii=False),
                    datetime.fromisoformat(evidence.collected_at),
                )
                await _audit(
                    conn,
                    actor,
                    "evidence",
                    evidence.id,
                    "evidence.create",
                    None,
                    {"tool": evidence.tool, "source": evidence.source, "ticket_id": evidence.ticket_id},
                )
        return evidence

    async def list_evidence(self, actor: Actor, ticket_id: str) -> list[Evidence]:
        actor.check("ticket.view_any")
        rows = await self._pool.fetch(
            "SELECT * FROM evidence WHERE ticket_id = $1 ORDER BY collected_at", uuid.UUID(ticket_id)
        )
        return [
            Evidence(
                id=str(r["id"]),
                ticket_id=str(r["ticket_id"]),
                tool=r["tool"],
                source=r["source"],
                data=json.loads(r["data"]),
                collected_at=r["collected_at"].isoformat(),
            )
            for r in rows
        ]

    async def create_proposal(self, actor: Actor, proposal: ActionProposal) -> ActionProposal:
        actor.check("proposal.create")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO action_proposals (id, ticket_id, action, params, evidence_ids, risk, created_by)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
                    """,
                    uuid.UUID(proposal.id),
                    uuid.UUID(proposal.ticket_id),
                    proposal.action,
                    json.dumps(proposal.params, ensure_ascii=False),
                    json.dumps(proposal.evidence_ids, ensure_ascii=False),
                    proposal.risk,
                    actor.id,
                )
                await _audit(
                    conn,
                    actor,
                    "proposal",
                    proposal.id,
                    "proposal.create",
                    None,
                    {"action": proposal.action, "risk": proposal.risk, "ticket_id": proposal.ticket_id},
                )
        return proposal

    async def approve_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        decision: str,  # approved | denied | modified
        modified_params: dict[str, Any] | None = None,
        note: str = "",
    ) -> Approval:
        """审批决议：行锁 + 状态检查拒绝并发重复决议。"""
        actor.check("proposal.approve")
        if decision not in ("approved", "denied", "modified"):
            raise ValueError(f"非法决议 {decision!r}")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM action_proposals WHERE id = $1 FOR UPDATE", uuid.UUID(proposal_id)
                )
                if row is None:
                    raise NotFoundError(f"提案 {proposal_id} 不存在")
                if row["status"] != "proposed":
                    raise ApprovalConflictError(f"提案 {proposal_id} 已决议（status={row['status']}）")
                version = await conn.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM approvals WHERE proposal_id = $1",
                    uuid.UUID(proposal_id),
                )
                approval_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO approvals (id, proposal_id, ticket_id, approver, decision, modified_params, note, version)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                    """,
                    approval_id,
                    uuid.UUID(proposal_id),
                    uuid.UUID(str(row["ticket_id"])),
                    actor.id,
                    decision,
                    json.dumps(modified_params, ensure_ascii=False) if modified_params is not None else None,
                    note,
                    int(version),
                )
                new_status = "approved" if decision in ("approved", "modified") else "denied"
                await conn.execute(
                    "UPDATE action_proposals SET status = $2 WHERE id = $1",
                    uuid.UUID(proposal_id),
                    new_status,
                )
                await _audit(
                    conn,
                    actor,
                    "approval",
                    str(approval_id),
                    "proposal.approve",
                    None,
                    {"proposal_id": proposal_id, "decision": decision, "version": int(version)},
                )
        return Approval(
            id=str(approval_id),
            proposal_id=proposal_id,
            ticket_id=str(row["ticket_id"]),
            approver=actor.id,
            decision=decision,
            modified_params=modified_params,
            note=note,
            decided_at=utc_now_iso(),
            version=int(version),
        )

    async def execute_proposal(self, actor: Actor, proposal_id: str) -> ExecutionRecord:
        """受控执行：幂等键唯一约束 + 高风险必须已审批。

        同一 proposal 重复调用返回同一执行记录（幂等）；未审批的高风险
        提案抛 ApprovalRequiredError。
        """
        actor.check("execution.run")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM action_proposals WHERE id = $1 FOR UPDATE", uuid.UUID(proposal_id)
                )
                if row is None:
                    raise NotFoundError(f"提案 {proposal_id} 不存在")
                proposal = ActionProposal(
                    id=str(row["id"]),
                    ticket_id=str(row["ticket_id"]),
                    action=row["action"],
                    params=json.loads(row["params"]),
                    evidence_ids=json.loads(row["evidence_ids"]),
                    risk=row["risk"],
                    created_by=row["created_by"],
                    created_at=row["created_at"].isoformat(),
                )
                idempotency_key = next_idempotency_key(proposal_id, proposal.action)
                existing = await conn.fetchrow(
                    "SELECT * FROM executions WHERE idempotency_key = $1", idempotency_key
                )
                if existing is not None:
                    return ExecutionRecord(
                        id=str(existing["id"]),
                        proposal_id=proposal_id,
                        ticket_id=str(existing["ticket_id"]),
                        idempotency_key=idempotency_key,
                        status=existing["status"],
                        attempts=int(existing["attempts"]),
                        result=json.loads(existing["result"]) if existing["result"] else None,
                        started_at=existing["started_at"].isoformat() if existing["started_at"] else None,
                        finished_at=existing["finished_at"].isoformat() if existing["finished_at"] else None,
                    )
                approved = row["status"] == "approved"
                try:
                    assert_executable(proposal, approved=approved, already_executed=False)
                except ApprovalRequiredError:
                    raise
                execution_id = uuid.uuid4()
                exec_row = await conn.fetchrow(
                    """
                    INSERT INTO executions (id, proposal_id, ticket_id, idempotency_key, status, attempts, result, started_at, finished_at)
                    VALUES ($1, $2, $3, $4, 'succeeded', 1, $5::jsonb, NOW(), NOW())
                    RETURNING *
                    """,
                    execution_id,
                    uuid.UUID(proposal_id),
                    uuid.UUID(proposal.ticket_id),
                    idempotency_key,
                    json.dumps({"ok": True, "action": proposal.action}, ensure_ascii=False),
                )
                await conn.execute(
                    "UPDATE action_proposals SET status = 'executed' WHERE id = $1", uuid.UUID(proposal_id)
                )
                await _audit(
                    conn,
                    actor,
                    "execution",
                    str(execution_id),
                    "execution.run",
                    None,
                    {"proposal_id": proposal_id, "idempotency_key": idempotency_key},
                )
        assert exec_row is not None
        return ExecutionRecord(
            id=str(exec_row["id"]),
            proposal_id=proposal_id,
            ticket_id=str(exec_row["ticket_id"]),
            idempotency_key=idempotency_key,
            status=exec_row["status"],
            attempts=int(exec_row["attempts"]),
            result=json.loads(exec_row["result"]) if exec_row["result"] else None,
            started_at=exec_row["started_at"].isoformat() if exec_row["started_at"] else None,
            finished_at=exec_row["finished_at"].isoformat() if exec_row["finished_at"] else None,
        )

    async def audit_for(self, actor: Actor, entity: str, entity_id: str) -> list[AuditEvent]:
        actor.check("audit.read")
        rows = await self._pool.fetch(
            "SELECT * FROM audit_events WHERE entity = $1 AND entity_id = $2 ORDER BY created_at",
            entity,
            entity_id,
        )
        return [
            AuditEvent(
                id=str(r["id"]),
                entity=r["entity"],
                entity_id=r["entity_id"],
                action=r["action"],
                actor=r["actor"],
                actor_role=r["actor_role"],
                before=json.loads(r["before"]) if r["before"] else None,
                after=json.loads(r["after"]) if r["after"] else None,
                created_at=r["created_at"].isoformat(),
            )
            for r in rows
        ]
