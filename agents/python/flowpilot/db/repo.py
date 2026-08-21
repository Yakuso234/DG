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

from flowpilot.action_runner import BusinessActionRunner, MockBusinessActionRunner
from flowpilot.domain.executor import (
    ParamValidationError,
    assert_executable,
    next_idempotency_key,
    validate_modified_params,
    validate_params,
)
from flowpilot.domain.models import (
    ActionProposal,
    AgentRun,
    Approval,
    AuditEvent,
    Evidence,
    ExecutionRecord,
    Ticket,
    utc_now_iso,
)
from flowpilot.domain.rbac import Actor, PermissionDeniedError
from flowpilot.domain.status import TicketStatus


class NotFoundError(LookupError):
    pass


class VersionConflictError(RuntimeError):
    """乐观锁冲突：并发修改被拒绝。"""


class ApprovalConflictError(RuntimeError):
    """审批并发冲突：提案已被其他人决议。"""


class StatePreconditionError(RuntimeError):
    """状态机顺序合法，但缺少进入目标状态所需的领域数据。"""


class IdempotencyConflictError(RuntimeError):
    """同一领域 ID 已存在，但内容与本次重试不一致。"""


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


def _row_to_execution(row: asyncpg.Record) -> ExecutionRecord:
    return ExecutionRecord(
        id=str(row["id"]),
        proposal_id=str(row["proposal_id"]),
        ticket_id=str(row["ticket_id"]),
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        attempts=int(row["attempts"]),
        result=json.loads(row["result"]) if row["result"] else None,
        started_at=row["started_at"].isoformat() if row["started_at"] else None,
        finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
    )


def _row_to_agent_run(row: asyncpg.Record) -> AgentRun:
    return AgentRun(
        id=str(row["id"]),
        ticket_id=str(row["ticket_id"]),
        agent=row["agent"],
        input_summary=row["input_summary"],
        output=json.loads(row["output"]) if row["output"] else {},
        model=row["model"],
        tokens=json.loads(row["tokens"]) if row["tokens"] else None,
        latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
        trace_id=row["trace_id"] or "",
        created_at=row["created_at"].isoformat(),
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
    def __init__(self, pool: asyncpg.Pool, action_runner: BusinessActionRunner | None = None) -> None:
        self._pool = pool
        self._action_runner = action_runner or MockBusinessActionRunner()

    async def _assert_transition_preconditions(
        self, conn: asyncpg.Connection, ticket_id: str, target: TicketStatus
    ) -> None:
        """校验状态机之外的数据不变量，不能只依赖 API/Agent 调用顺序。"""
        ticket_uuid = uuid.UUID(ticket_id)
        if target is TicketStatus.PROPOSED:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM action_proposals WHERE ticket_id = $1)", ticket_uuid
            )
            if not exists:
                raise StatePreconditionError("进入 PROPOSED 前必须存在有效 ActionProposal")
        elif target is TicketStatus.WAITING_APPROVAL:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM action_proposals WHERE ticket_id = $1 AND status = 'proposed')",
                ticket_uuid,
            )
            if not exists:
                raise StatePreconditionError("进入 WAITING_APPROVAL 前必须存在待审批提案")
        elif target is TicketStatus.EXECUTING:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM action_proposals WHERE ticket_id = $1 AND status = 'approved')",
                ticket_uuid,
            )
            if not exists:
                raise StatePreconditionError("进入 EXECUTING 前必须存在已批准提案")
        elif target is TicketStatus.RESOLVED:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM executions WHERE ticket_id = $1 AND status = 'succeeded')", ticket_uuid
            )
            if not exists:
                raise StatePreconditionError("进入 RESOLVED 前必须存在成功的执行记录")

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
        rows = await self._pool.fetch("SELECT * FROM tickets ORDER BY created_at DESC LIMIT $1", min(limit, 200))
        return [_row_to_ticket(r) for r in rows]

    async def transition(self, actor: Actor, ticket_id: str, target: TicketStatus) -> Ticket:
        """状态转移（乐观锁）：WHERE version 匹配失败即拒绝并发修改。"""
        from flowpilot.domain.rbac import can_transition_to
        from flowpilot.domain.status import assert_legal_transition

        actor.check("ticket.transition")
        if not can_transition_to(actor.role, target):
            raise PermissionDeniedError(actor.role, f"transition:{target.value}", "角色不允许转移到该状态")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM tickets WHERE id = $1 FOR UPDATE", uuid.UUID(ticket_id))
                if row is None:
                    raise NotFoundError(f"工单 {ticket_id} 不存在")
                ticket = _row_to_ticket(row)
                assert_legal_transition(ticket.status, target)
                await self._assert_transition_preconditions(conn, ticket_id, target)
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
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO evidence (id, ticket_id, tool, source, data, collected_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                    """,
                    uuid.UUID(evidence.id),
                    uuid.UUID(evidence.ticket_id),
                    evidence.tool,
                    evidence.source,
                    json.dumps(evidence.data, ensure_ascii=False),
                    datetime.fromisoformat(evidence.collected_at),
                )
                if inserted is None:
                    existing = await conn.fetchrow("SELECT * FROM evidence WHERE id = $1", uuid.UUID(evidence.id))
                    if existing is None or (
                        str(existing["ticket_id"]) != evidence.ticket_id
                        or existing["tool"] != evidence.tool
                        or existing["source"] != evidence.source
                        or json.loads(existing["data"]) != evidence.data
                    ):
                        raise IdempotencyConflictError(f"Evidence {evidence.id} 已存在但内容不一致")
                    return evidence
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
        # 先阻断无效提案，保证进入 PROPOSED 的提案满足动作合同；执行前仍会二次校验。
        validate_params(proposal.action, proposal.params)
        if proposal.params.get("ticket_id") != proposal.ticket_id:
            raise ParamValidationError("提案 params.ticket_id 必须与所属 ticket_id 一致")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO action_proposals (id, ticket_id, action, params, evidence_ids, risk, created_by)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                    """,
                    uuid.UUID(proposal.id),
                    uuid.UUID(proposal.ticket_id),
                    proposal.action,
                    json.dumps(proposal.params, ensure_ascii=False),
                    json.dumps(proposal.evidence_ids, ensure_ascii=False),
                    proposal.risk,
                    actor.id,
                )
                if inserted is None:
                    existing = await conn.fetchrow(
                        "SELECT * FROM action_proposals WHERE id = $1", uuid.UUID(proposal.id)
                    )
                    if existing is None or (
                        str(existing["ticket_id"]) != proposal.ticket_id
                        or existing["action"] != proposal.action
                        or json.loads(existing["params"]) != proposal.params
                        or json.loads(existing["evidence_ids"]) != proposal.evidence_ids
                        or existing["risk"] != proposal.risk
                        or existing["created_by"] != actor.id
                    ):
                        raise IdempotencyConflictError(f"ActionProposal {proposal.id} 已存在但内容不一致")
                    return proposal
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

    async def record_agent_run(self, actor: Actor, run: AgentRun) -> AgentRun:
        """以稳定运行 ID 幂等保存工作流摘要，避免重启恢复重复生成展示记录。"""
        actor.check("agent_run.create")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO agent_runs (
                        id, ticket_id, agent, input_summary, output, model, tokens, latency_ms, trace_id
                    )
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9)
                    ON CONFLICT (id) DO NOTHING
                    RETURNING *
                    """,
                    uuid.UUID(run.id),
                    uuid.UUID(run.ticket_id),
                    run.agent,
                    run.input_summary,
                    json.dumps(run.output, ensure_ascii=False),
                    run.model,
                    json.dumps(run.tokens, ensure_ascii=False) if run.tokens is not None else None,
                    run.latency_ms,
                    run.trace_id,
                )
                if inserted is not None:
                    return _row_to_agent_run(inserted)
                existing = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", uuid.UUID(run.id))
                if existing is None or (
                    str(existing["ticket_id"]) != run.ticket_id
                    or existing["agent"] != run.agent
                    or existing["input_summary"] != run.input_summary
                    or json.loads(existing["output"]) != run.output
                    or existing["model"] != run.model
                    or (json.loads(existing["tokens"]) if existing["tokens"] else None) != run.tokens
                    or (existing["trace_id"] or "") != run.trace_id
                ):
                    raise IdempotencyConflictError(f"AgentRun {run.id} 已存在但内容不一致")
                # 同一次 checkpoint 重放的时延会自然变化；保留首次落库值，不能
                # 因观测字段波动把安全重试误判成业务冲突。
                return _row_to_agent_run(existing)

    async def list_agent_runs(self, actor: Actor, ticket_id: str) -> list[AgentRun]:
        actor.check("ticket.view_any")
        rows = await self._pool.fetch(
            "SELECT * FROM agent_runs WHERE ticket_id = $1 ORDER BY created_at", uuid.UUID(ticket_id)
        )
        return [_row_to_agent_run(row) for row in rows]

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
                if actor.id == row["created_by"]:
                    raise PermissionDeniedError(actor.role, "proposal.approve", "创建人不能审批自己的提案")
                if decision == "modified":
                    if modified_params is None:
                        raise ParamValidationError("modified 决议必须提供 modified_params")
                    if modified_params.get("ticket_id") != str(row["ticket_id"]):
                        raise ParamValidationError("modified_params.ticket_id 必须与所属 ticket_id 一致")
                    validate_modified_params(row["action"], json.loads(row["params"]), modified_params)
                elif modified_params is not None:
                    raise ParamValidationError("只有 modified 决议可以提供 modified_params")
                version = await conn.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM approvals WHERE proposal_id = $1",
                    uuid.UUID(proposal_id),
                )
                approval_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO approvals
                        (id, proposal_id, ticket_id, approver, decision, modified_params, note, version)
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
                    "UPDATE action_proposals SET status = $2, params = COALESCE($3::jsonb, params) WHERE id = $1",
                    uuid.UUID(proposal_id),
                    new_status,
                    json.dumps(modified_params, ensure_ascii=False) if decision == "modified" else None,
                )
                await _audit(
                    conn,
                    actor,
                    "approval",
                    str(approval_id),
                    "proposal.approve",
                    None,
                    {
                        "proposal_id": proposal_id,
                        "decision": decision,
                        "modified_params": modified_params,
                        "version": int(version),
                    },
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
        """提交执行记录后调用业务适配器，并把成功或失败结果持久化。

        先以唯一幂等键提交 ``running`` 记录并释放事务，再执行有副作用的
        业务调用；重复请求只返回原记录，避免在数据库事务内等待外部调用。
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
                existing = await conn.fetchrow("SELECT * FROM executions WHERE idempotency_key = $1", idempotency_key)
                if existing is not None:
                    return _row_to_execution(existing)
                approved = row["status"] == "approved"
                assert_executable(proposal, approved=approved, already_executed=False)
                execution_id = uuid.uuid4()
                exec_row = await conn.fetchrow(
                    """
                    INSERT INTO executions
                        (id, proposal_id, ticket_id, idempotency_key, status, attempts, result,
                         started_at, finished_at)
                    VALUES ($1, $2, $3, $4, 'running', 1, NULL, NOW(), NULL)
                    RETURNING *
                    """,
                    execution_id,
                    uuid.UUID(proposal_id),
                    uuid.UUID(proposal.ticket_id),
                    idempotency_key,
                )
                await _audit(
                    conn,
                    actor,
                    "execution",
                    str(execution_id),
                    "execution.started",
                    None,
                    {"proposal_id": proposal_id, "idempotency_key": idempotency_key, "status": "running"},
                )
        assert exec_row is not None

        try:
            result = await self._action_runner.run(proposal)
            outcome_status = "succeeded"
            audit_action = "execution.succeeded"
        except Exception as exc:
            result = {
                "ok": False,
                "action": proposal.action,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            }
            outcome_status = "failed"
            audit_action = "execution.failed"

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                completed = await conn.fetchrow(
                    """
                    UPDATE executions SET status = $2, result = $3::jsonb, finished_at = NOW()
                    WHERE id = $1 AND status = 'running'
                    RETURNING *
                    """,
                    execution_id,
                    outcome_status,
                    json.dumps(result, ensure_ascii=False),
                )
                if completed is None:
                    raise RuntimeError(f"执行记录 {execution_id} 未处于 running 状态，无法写入结果")
                if outcome_status == "succeeded":
                    await conn.execute(
                        "UPDATE action_proposals SET status = 'executed' WHERE id = $1", uuid.UUID(proposal_id)
                    )
                await _audit(
                    conn,
                    actor,
                    "execution",
                    str(execution_id),
                    audit_action,
                    {"status": "running"},
                    {"status": outcome_status, "result": result},
                )
        return _row_to_execution(completed)

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
