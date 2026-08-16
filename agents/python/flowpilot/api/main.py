"""FlowPilot API — Phase 1 确定性工单闭环（无 LLM）。

身份：Phase 1 用 x-user-id / x-user-role 头（见 flowpilot.domain.rbac），
Phase 2 接入上游 JWT 中间件（shared/auth.py）后替换 actor_from_headers。

工厂模式：`build_app(pool)` 注入连接池供测试使用（httpx ASGITransport +
testcontainers）；模块级 `app = build_app()` 供 uvicorn 启动，连接池由
lifespan 按环境变量 FLOWPILOT_DATABASE_URL / DATABASE_URL 创建。

启动：uvicorn flowpilot.api.main:app --port 8090
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import asyncpg
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
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


def _repo(request: Request) -> TicketRepo:
    pool = request.app.state.pool
    if pool is None:
        raise RuntimeError("DB 池未初始化（lifespan 失败）")
    return TicketRepo(pool)


def _actor_from_request(request: Request):
    headers = request.headers
    return _actor(
        headers.get("x-user-id"),
        headers.get("x-user-role"),
        headers.get("x-agent-id"),
        headers.get("x-agent-role"),
    )


_ERROR_STATUS: dict[type[Exception], int] = {
    NotFoundError: 404,
    PermissionDeniedError: 403,
    IllegalTransitionError: 409,
    VersionConflictError: 409,
    ApprovalConflictError: 409,
    ApprovalRequiredError: 409,
    ParamValidationError: 422,
    ExecutionError: 409,
}


def _register_error_handlers(app: FastAPI) -> None:
    """把领域异常集中映射为 HTTP 状态码（覆盖路由体与依赖中的异常）。"""

    def _make_handler(exc_type: type[Exception], status: int):
        async def _handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": f"{exc_type.__name__}: {exc}"})

        return _handler

    for exc_type, status in _ERROR_STATUS.items():
        app.add_exception_handler(exc_type, _make_handler(exc_type, status))


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


def build_app(pool: asyncpg.Pool | None = None) -> FastAPI:
    app = FastAPI(title="FlowPilot API (Phase 1)", version="0.1.0")
    app.state.pool = pool
    _register_error_handlers(app)

    if pool is None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _lifespan(app: FastAPI):  # pragma: no cover - 需要真实 DB
            dsn = os.environ.get("FLOWPILOT_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
            if not dsn:
                raise RuntimeError("缺少 FLOWPILOT_DATABASE_URL / DATABASE_URL")
            app.state.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
            try:
                yield
            finally:
                await app.state.pool.close()
                app.state.pool = None

        app.router.lifespan_context = _lifespan

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "flowpilot-api"}

    @app.post("/api/tickets", status_code=201)
    async def create_ticket(body: TicketCreate, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        ticket = await _repo(request).create_ticket(actor, body.title, body.description, body.priority)
        return ticket.to_dict()

    @app.get("/api/tickets")
    async def list_tickets(request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        tickets = await _repo(request).list_tickets(actor)
        return [t.to_dict() for t in tickets]

    @app.get("/api/tickets/{ticket_id}")
    async def get_ticket(ticket_id: str, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        ticket = await _repo(request).get_ticket(actor, ticket_id)
        return ticket.to_dict()

    @app.post("/api/tickets/{ticket_id}/transitions")
    async def transition_ticket(ticket_id: str, body: TransitionBody, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        target = TicketStatus(body.target)
        ticket = await _repo(request).transition(actor, ticket_id, target)
        return ticket.to_dict()

    @app.post("/api/tickets/{ticket_id}/evidence", status_code=201)
    async def add_evidence(ticket_id: str, body: EvidenceCreate, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        evidence = Evidence(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            tool=body.tool,
            source=body.source,
            data=body.data,
            collected_at=utc_now_iso(),
        )
        saved = await _repo(request).add_evidence(actor, evidence)
        return saved.to_dict()

    @app.get("/api/tickets/{ticket_id}/evidence")
    async def list_evidence(ticket_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        items = await _repo(request).list_evidence(actor, ticket_id)
        return [e.to_dict() for e in items]

    @app.post("/api/tickets/{ticket_id}/proposals", status_code=201)
    async def create_proposal(ticket_id: str, body: ProposalCreate, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
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
        saved = await _repo(request).create_proposal(actor, proposal)
        return saved.to_dict()

    @app.post("/api/proposals/{proposal_id}/approvals", status_code=201)
    async def approve_proposal(proposal_id: str, body: ApprovalCreate, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        approval = await _repo(request).approve_proposal(
            actor, proposal_id, body.decision, body.modified_params, body.note
        )
        return approval.to_dict()

    @app.post("/api/proposals/{proposal_id}/execute")
    async def execute_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        record = await _repo(request).execute_proposal(actor, proposal_id)
        return record.to_dict()

    @app.get("/api/audit/{entity}/{entity_id}")
    async def audit_events(entity: str, entity_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        events = await _repo(request).audit_for(actor, entity, entity_id)
        return [e.to_dict() for e in events]

    return app


app = build_app()
