"""FlowPilot API — Phase 1 确定性工单闭环（无 LLM）。

身份：Phase 1 用 x-user-id / x-user-role 头（见 flowpilot.domain.rbac），
Phase 2 接入上游 JWT 中间件（shared/auth.py）后替换 actor_from_headers。
启动：uvicorn flowpilot.api.main:app --port 8090
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from flowpilot.db import ApprovalConflictError, NotFoundError, TicketRepo, VersionConflictError
from flowpilot.domain.executor import (
    ApprovalRequiredError,
    ExecutionError,
    ParamValidationError,
)
from flowpilot.domain.models import ActionProposal, Evidence, utc_now_iso
from flowpilot.domain.rbac import PermissionDeniedError, actor_from_headers
from flowpilot.domain.status import IllegalTransitionError, TicketStatus

app = FastAPI(title="FlowPilot API (Phase 1)", version="0.1.0")

_pool: asyncpg.Pool | None = None


def _repo() -> TicketRepo:
    if _pool is None:
        raise RuntimeError("DB 池未初始化（lifespan 失败）")
    return TicketRepo(_pool)


def _actor(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_role: str | None = Header(default=None),
):
    return actor_from_headers(
        {
            "x-user-id": x_user_id,
            "x-user-role": x_user_role,
            "x-agent-id": x_agent_id,
            "x-agent-role": x_agent_role,
        }
    )


@app.on_event("startup")
async def _startup() -> None:  # pragma: no cover - 需要真实 DB
    import os

    global _pool
    dsn = os.environ.get("FLOWPILOT_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        raise RuntimeError("缺少 FLOWPILOT_DATABASE_URL / DATABASE_URL")
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)


@app.on_event("shutdown")
async def _shutdown() -> None:  # pragma: no cover
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "flowpilot-api"}


class TicketCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: int = Field(default=3, ge=1, le=5)


class EvidenceCreate(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)


class ProposalCreate(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    risk: str = Field(default="low", pattern="^(low|high)$")


class ApprovalCreate(BaseModel):
    decision: str = Field(pattern="^(approved|denied|modified)$")
    modified_params: dict[str, Any] | None = None
    note: str = ""


class TransitionBody(BaseModel):
    target: str


def _to_http_error(exc: Exception) -> HTTPException:
    mapping: list[tuple[type[Exception], int]] = [
        (NotFoundError, 404),
        (PermissionDeniedError, 403),
        (IllegalTransitionError, 409),
        (VersionConflictError, 409),
        (ApprovalConflictError, 409),
        (ApprovalRequiredError, 409),
        (ParamValidationError, 422),
        (ExecutionError, 409),
    ]
    for exc_type, status in mapping:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")
    raise exc


@app.post("/api/tickets", status_code=201)
async def create_ticket(body: TicketCreate, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    try:
        ticket = await _repo().create_ticket(actor, body.title, body.description, body.priority)
    except Exception as exc:  # noqa: BLE001 - 统一错误映射
        raise _to_http_error(exc) from exc
    return ticket.to_dict()


@app.get("/api/tickets")
async def list_tickets(request: Request) -> list[dict[str, Any]]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    tickets = await _repo().list_tickets(actor)
    return [t.to_dict() for t in tickets]


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    try:
        ticket = await _repo().get_ticket(actor, ticket_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return ticket.to_dict()


@app.post("/api/tickets/{ticket_id}/transitions")
async def transition_ticket(ticket_id: str, body: TransitionBody, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    try:
        target = TicketStatus(body.target)
        ticket = await _repo().transition(actor, ticket_id, target)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return ticket.to_dict()


@app.post("/api/tickets/{ticket_id}/evidence", status_code=201)
async def add_evidence(ticket_id: str, body: EvidenceCreate, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    evidence = Evidence(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        tool=body.tool,
        source=body.source,
        data=body.data,
        collected_at=utc_now_iso(),
    )
    try:
        saved = await _repo().add_evidence(actor, evidence)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return saved.to_dict()


@app.get("/api/tickets/{ticket_id}/evidence")
async def list_evidence(ticket_id: str, request: Request) -> list[dict[str, Any]]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    items = await _repo().list_evidence(actor, ticket_id)
    return [e.to_dict() for e in items]


@app.post("/api/tickets/{ticket_id}/proposals", status_code=201)
async def create_proposal(ticket_id: str, body: ProposalCreate, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    proposal = ActionProposal(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        action=body.action,
        params=body.params,
        evidence_ids=body.evidence_ids,
        risk=body.risk,
        created_by=actor.id,
        created_at=utc_now_iso(),
    )
    try:
        saved = await _repo().create_proposal(actor, proposal)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return saved.to_dict()


@app.post("/api/proposals/{proposal_id}/approvals", status_code=201)
async def approve_proposal(proposal_id: str, body: ApprovalCreate, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    try:
        approval = await _repo().approve_proposal(
            actor, proposal_id, body.decision, body.modified_params, body.note
        )
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return approval.to_dict()


@app.post("/api/proposals/{proposal_id}/execute")
async def execute_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    try:
        record = await _repo().execute_proposal(actor, proposal_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return record.to_dict()


@app.get("/api/audit/{entity}/{entity_id}")
async def audit_events(entity: str, entity_id: str, request: Request) -> list[dict[str, Any]]:
    actor = _actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-role"),
        request.headers.get("x-agent-id"),
        request.headers.get("x-agent-role"),
    )
    events = await _repo().audit_for(actor, entity, entity_id)
    return [e.to_dict() for e in events]
