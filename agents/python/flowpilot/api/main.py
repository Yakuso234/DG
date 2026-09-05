"""FlowPilot API — Phase 1 确定性工单闭环（无 LLM）。

身份：Phase 1 用 x-user-id / x-user-role 头（见 flowpilot.domain.rbac），
Phase 2 接入上游 JWT 中间件（shared/auth.py）后替换 actor_from_headers。

工厂模式：`build_app(pool)` 注入连接池供测试使用（httpx ASGITransport +
testcontainers）；模块级 `app = build_app()` 供 uvicorn 启动，连接池由
lifespan 按环境变量 FLOWPILOT_DATABASE_URL / DATABASE_URL 创建。

启动：uvicorn flowpilot.api.main:app --port 8090
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from flowpilot.action_runner import BusinessActionRunner, MockBusinessActionRunner
from flowpilot.approval_workflow import (
    ApprovalWorkflowMismatchError,
    ApprovalWorkflowResult,
    ApprovalWorkflowService,
)
from flowpilot.auth import FlowPilotAuthConfig, FlowPilotAuthError
from flowpilot.db import (
    ApprovalConflictError,
    IdempotencyConflictError,
    NotFoundError,
    StatePreconditionError,
    TicketRepo,
    VersionConflictError,
)
from flowpilot.domain.executor import (
    ApprovalRequiredError,
    ExecutionError,
    ParamValidationError,
)
from flowpilot.domain.models import ActionProposal, Evidence, utc_now_iso
from flowpilot.domain.rbac import Actor, PermissionDeniedError, Role, actor_from_headers
from flowpilot.domain.status import IllegalTransitionError, TicketStatus
from flowpilot.execution_reconciliation import ExecutionReconciliationService
from flowpilot.observability import TRACE_ID_HEADER, current_trace_id, is_valid_trace_id, new_trace_id, set_trace_id
from flowpilot.structured_model import structured_model_from_env
from flowpilot.sw_video_ops import gateway_from_env
from flowpilot.sw_video_recovery import SwVideoRecoveryActionRunner
from flowpilot.ticket_workflow import TicketWorkflowService, TicketWorkflowStartResult, TicketWorkflowStateError
from flowpilot.workflow_runtime import open_workflow_runtime


class WorkflowUnavailableError(RuntimeError):
    """当前 API 进程未装配审批恢复工作流。"""


class TraceIdMismatchError(ValueError):
    """调用方提供的请求 TraceId 与工作流业务 TraceId 不一致。"""


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
    return TicketRepo(pool, request.app.state.action_runner)


def _reconciliation(request: Request) -> ExecutionReconciliationService:
    service: ExecutionReconciliationService | None = request.app.state.reconciliation_service
    if service is None:
        service = ExecutionReconciliationService(_repo(request), request.app.state.action_runner)
        request.app.state.reconciliation_service = service
    return service


def _actor_from_request(request: Request) -> Actor:
    auth_config: FlowPilotAuthConfig = request.app.state.auth_config
    if auth_config.mode == "jwt-local":
        return auth_config.actor_from_bearer(request.headers.get("authorization"))
    headers = request.headers
    return _actor(
        headers.get("x-user-id"),
        headers.get("x-user-role"),
        headers.get("x-agent-id"),
        headers.get("x-agent-role"),
    )


_ERROR_STATUS: dict[type[Exception], int] = {
    FlowPilotAuthError: 401,
    NotFoundError: 404,
    PermissionDeniedError: 403,
    IllegalTransitionError: 409,
    VersionConflictError: 409,
    ApprovalConflictError: 409,
    IdempotencyConflictError: 409,
    ApprovalWorkflowMismatchError: 409,
    TicketWorkflowStateError: 409,
    ApprovalRequiredError: 409,
    StatePreconditionError: 409,
    ParamValidationError: 422,
    TraceIdMismatchError: 422,
    ExecutionError: 409,
    WorkflowUnavailableError: 503,
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


class WorkflowApprovalCreate(ApprovalCreate):
    thread_id: str = Field(min_length=1, max_length=128)


class WorkflowStartCreate(BaseModel):
    creator_id: int = Field(gt=0)
    video_id: int = Field(gt=0)
    trace_id: str | None = Field(default=None, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)


def _cors_origins_from_env() -> list[str]:
    """解析本地工作台允许的浏览器 Origin，不允许通配任意站点。"""

    configured = os.environ.get("FLOWPILOT_CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def build_app(
    pool: asyncpg.Pool | None = None,
    action_runner: BusinessActionRunner | None = None,
    approval_workflow: ApprovalWorkflowService | None = None,
    ticket_workflow: TicketWorkflowService | None = None,
    auth_config: FlowPilotAuthConfig | None = None,
) -> FastAPI:
    from shared.telemetry import instrument_fastapi

    if pool is None:
        from shared.telemetry import setup_telemetry

        setup_telemetry(service_name=os.environ.get("OTEL_SERVICE_NAME", "flowpilot-api"))
    app = FastAPI(title="FlowPilot API (Phase 1)", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_env(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Trace-Id", "X-User-Id", "X-User-Role"],
    )
    instrument_fastapi(app)
    app.state.pool = pool
    app.state.action_runner = action_runner or MockBusinessActionRunner()
    app.state.approval_workflow = approval_workflow
    app.state.ticket_workflow = ticket_workflow
    app.state.auth_config = auth_config or FlowPilotAuthConfig.from_env()
    app.state.reconciliation_service = (
        ExecutionReconciliationService(TicketRepo(pool, app.state.action_runner), app.state.action_runner)
        if pool is not None
        else None
    )
    _register_error_handlers(app)

    @app.middleware("http")
    async def trace_id_context(request: Request, call_next):
        incoming = request.headers.get(TRACE_ID_HEADER)
        if incoming is not None and not is_valid_trace_id(incoming):
            trace_id = new_trace_id()
            set_trace_id(trace_id)
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Trace-Id 只能包含字母、数字、点、下划线、冒号或连字符，且长度为 1-128"},
                headers={TRACE_ID_HEADER: trace_id},
            )
        set_trace_id(incoming or new_trace_id())
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = current_trace_id()
        return response

    if pool is None:

        @asynccontextmanager
        async def _lifespan(app: FastAPI):  # pragma: no cover - 需要真实 DB
            dsn = os.environ.get("FLOWPILOT_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
            if not dsn:
                raise RuntimeError("缺少 FLOWPILOT_DATABASE_URL / DATABASE_URL")
            async with AsyncExitStack() as stack:
                app.state.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
                stack.push_async_callback(app.state.pool.close)
                if action_runner is None:
                    runner_mode = os.environ.get("FLOWPILOT_ACTION_RUNNER", "mock").strip().lower()
                    if runner_mode == "sw-video-recovery":
                        sw_runner = SwVideoRecoveryActionRunner.from_env()
                        stack.push_async_callback(sw_runner.aclose)
                        app.state.action_runner = sw_runner
                    elif runner_mode != "mock":
                        raise RuntimeError(
                            f"FLOWPILOT_ACTION_RUNNER 只能是 mock 或 sw-video-recovery，实际为 {runner_mode!r}"
                        )
                reconcile_enabled = os.environ.get("FLOWPILOT_RECONCILIATION_ENABLED", "false").lower() in {
                    "1",
                    "true",
                    "yes",
                }
                reconcile_interval = max(1, int(os.environ.get("FLOWPILOT_RECONCILIATION_INTERVAL_SECONDS", "5")))
                reconcile_batch_size = max(
                    1, min(200, int(os.environ.get("FLOWPILOT_RECONCILIATION_BATCH_SIZE", "50")))
                )
                reconcile_max_attempts = max(1, int(os.environ.get("FLOWPILOT_RECONCILIATION_MAX_ATTEMPTS", "4")))
                app.state.reconciliation_service = ExecutionReconciliationService(
                    TicketRepo(app.state.pool, app.state.action_runner),
                    app.state.action_runner,
                    max_attempts=reconcile_max_attempts,
                )
                reconcile_task: asyncio.Task[None] | None = None
                if reconcile_enabled:

                    async def _reconcile_loop() -> None:
                        while True:
                            try:
                                await app.state.reconciliation_service.run_once(limit=reconcile_batch_size)
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                # 单批异常不能终止后台对账；明细由 execution 审计与 OTel 查询。
                                pass
                            await asyncio.sleep(reconcile_interval)

                    reconcile_task = asyncio.create_task(_reconcile_loop(), name="flowpilot-reconciliation")
                enabled = os.environ.get("FLOWPILOT_WORKFLOW_ENABLED", "false").lower() in {"1", "true", "yes"}
                try:
                    if enabled:
                        checkpoint_path = os.environ.get("FLOWPILOT_CHECKPOINT_PATH", "").strip()
                        if not checkpoint_path:
                            raise RuntimeError("启用工作流时必须设置 FLOWPILOT_CHECKPOINT_PATH")
                        gateway = gateway_from_env()
                        model = structured_model_from_env()
                        close_gateway = getattr(gateway, "aclose", None)
                        if callable(close_gateway):
                            stack.push_async_callback(close_gateway)
                        handler_actor = Actor(
                            os.environ.get("FLOWPILOT_HANDLER_ACTOR_ID", "flowpilot-handler"), Role.HANDLER
                        )
                        service_actor = Actor(
                            os.environ.get("FLOWPILOT_EXECUTOR_ACTOR_ID", "flowpilot-action-executor"), Role.SERVICE
                        )
                        runtime = await stack.enter_async_context(
                            open_workflow_runtime(
                                TicketRepo(app.state.pool, app.state.action_runner),
                                gateway,
                                checkpoint_path=checkpoint_path,
                                handler_actor=handler_actor,
                                service_actor=service_actor,
                                model=model,
                            )
                        )
                        app.state.ticket_workflow = runtime.ticket_workflow
                        app.state.approval_workflow = runtime.approval_workflow
                    yield
                finally:
                    if reconcile_task is not None:
                        reconcile_task.cancel()
                        try:
                            await reconcile_task
                        except asyncio.CancelledError:
                            pass
                    app.state.pool = None
                    app.state.reconciliation_service = None
                    if enabled:
                        app.state.ticket_workflow = None
                        app.state.approval_workflow = None

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

    @app.get("/api/tickets/{ticket_id}/proposals")
    async def list_proposals(ticket_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        return [item.to_dict() for item in await _repo(request).list_proposals(actor, ticket_id)]

    @app.get("/api/proposals/{proposal_id}")
    async def get_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        return (await _repo(request).get_proposal(actor, proposal_id)).to_dict()

    @app.post("/api/proposals/{proposal_id}/approvals", status_code=201)
    async def approve_proposal(proposal_id: str, body: ApprovalCreate, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        approval = await _repo(request).approve_proposal(
            actor, proposal_id, body.decision, body.modified_params, body.note
        )
        return approval.to_dict()

    @app.post("/api/workflows/tickets/{ticket_id}/start", status_code=202)
    async def start_ticket_workflow(ticket_id: str, body: WorkflowStartCreate, request: Request) -> dict[str, Any]:
        workflow = request.app.state.ticket_workflow
        if workflow is None:
            raise WorkflowUnavailableError("工单 Agent 工作流尚未装配")
        _actor_from_request(request).check("ticket.transition")
        request_trace_id = request.headers.get(TRACE_ID_HEADER)
        if body.trace_id is not None and not is_valid_trace_id(body.trace_id):
            raise TraceIdMismatchError("请求体 trace_id 格式非法")
        if request_trace_id is not None and body.trace_id is not None and request_trace_id != body.trace_id:
            raise TraceIdMismatchError("请求头 X-Trace-Id 必须与工作流 trace_id 一致")
        trace_id = body.trace_id or current_trace_id()
        set_trace_id(trace_id)
        result: TicketWorkflowStartResult = await workflow.start(
            ticket_id=ticket_id,
            creator_id=body.creator_id,
            video_id=body.video_id,
            trace_id=trace_id,
            thread_id=body.thread_id,
        )
        return {
            "ticket_id": result.ticket_id,
            "thread_id": result.thread_id,
            "trace_id": trace_id,
            "ticket_target": result.ticket_target.value,
            "evidence": [item.to_dict() for item in result.evidence],
            "proposal": result.proposal.to_dict() if result.proposal is not None else None,
            "agent_run": result.agent_run.to_dict(),
            "steps": result.graph_state.get("steps", []),
        }

    @app.post("/api/workflows/proposals/{proposal_id}/approvals")
    async def decide_workflow_approval(
        proposal_id: str, body: WorkflowApprovalCreate, request: Request
    ) -> dict[str, Any]:
        """受控入口：审批落库、恢复同一图、匹配后才允许执行。"""
        workflow = request.app.state.approval_workflow
        if workflow is None:
            raise WorkflowUnavailableError("审批恢复工作流尚未装配")
        actor = _actor_from_request(request)
        result: ApprovalWorkflowResult = await workflow.decide(
            actor,
            proposal_id,
            body.decision,
            {"configurable": {"thread_id": body.thread_id}},
            modified_params=body.modified_params,
            note=body.note,
        )
        return {
            "approval": result.approval.to_dict(),
            "execution": result.execution.to_dict() if result.execution is not None else None,
            "ticket_target": result.ticket_target.value,
            "steps": result.graph_state.get("steps", []),
        }

    @app.post("/api/proposals/{proposal_id}/execute")
    async def execute_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        record = await _repo(request).execute_proposal(actor, proposal_id)
        return record.to_dict()

    @app.get("/api/tickets/{ticket_id}/executions")
    async def list_executions(ticket_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        return [item.to_dict() for item in await _repo(request).list_executions(actor, ticket_id)]

    @app.post("/api/executions/{execution_id}/reconcile")
    async def reconcile_execution(execution_id: str, request: Request) -> dict[str, Any]:
        actor = _actor_from_request(request)
        actor.check("execution.reconcile")
        return (await _reconciliation(request).reconcile(execution_id, actor=actor)).to_dict()

    @app.get("/api/tickets/{ticket_id}/runs")
    async def list_agent_runs(ticket_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        return [run.to_dict() for run in await _repo(request).list_agent_runs(actor, ticket_id)]

    @app.get("/api/audit/{entity}/{entity_id}")
    async def audit_events(entity: str, entity_id: str, request: Request) -> list[dict[str, Any]]:
        actor = _actor_from_request(request)
        events = await _repo(request).audit_for(actor, entity, entity_id)
        return [e.to_dict() for e in events]

    return app


app = build_app()
