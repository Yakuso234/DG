"""FlowPilot 主场景演示：真实 API/数据库 + Mock 外部系统 + 可替换模型。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import asyncpg
from httpx import ASGITransport, AsyncClient, HTTPStatusError, Response

from flowpilot.action_runner import MockBusinessActionRunner
from flowpilot.api.main import build_app
from flowpilot.db.repo import TicketRepo
from flowpilot.domain.rbac import Actor, Role
from flowpilot.structured_model import (
    FakeStructuredFlowPilotModel,
    StructuredFlowPilotModel,
    structured_model_from_env,
)
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot
from flowpilot.workflow_runtime import open_workflow_runtime

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INIT_SQL = _REPO_ROOT / "docker" / "postgres" / "init.sql"
_FLOWPILOT_SCHEMA_MARKER = "-- FlowPilot (DG) 工单域"

_SUBMITTER = {"x-user-id": "demo-submitter", "x-user-role": "submitter"}
_HANDLER = {"x-user-id": "demo-handler", "x-user-role": "handler"}
_APPROVER = {"x-user-id": "demo-approver", "x-user-role": "approver"}
_ADMIN = {"x-user-id": "demo-admin", "x-user-role": "admin"}


def _require_success(response: Response, stage: str) -> None:
    try:
        response.raise_for_status()
    except HTTPStatusError as exc:
        detail = response.text[:1000]
        raise RuntimeError(f"{stage}失败（HTTP {response.status_code}）：{detail}") from exc


async def _apply_schema(pool: asyncpg.Pool) -> None:
    if not _INIT_SQL.exists():
        raise RuntimeError(f"找不到本地演示 Schema：{_INIT_SQL}")
    async with pool.acquire() as connection:
        full_schema = _INIT_SQL.read_text(encoding="utf-8")
        _, marker, flowpilot_schema = full_schema.partition(_FLOWPILOT_SCHEMA_MARKER)
        if not marker:
            raise RuntimeError("docker/postgres/init.sql 缺少 FlowPilot Schema 标记")
        await connection.execute(f"{marker}{flowpilot_schema}")


async def run_demo(
    *,
    database_url: str,
    checkpoint_path: str,
    trace_id: str = "trace-demo-mock-1",
    initialize_schema: bool = True,
    model: StructuredFlowPilotModel | None = None,
) -> dict[str, Any]:
    """运行一次持久化审批主链路，并返回可用于面试展示的摘要。"""
    if not database_url.strip():
        raise ValueError("需要 FLOWPILOT_DATABASE_URL 或 --database-url")
    if not checkpoint_path.strip():
        raise ValueError("checkpoint_path 不能为空")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
    try:
        if initialize_schema:
            await _apply_schema(pool)
        runner = MockBusinessActionRunner()
        repo = TicketRepo(pool, runner)
        gateway = MockSwVideoOpsGateway(
            [
                VideoProcessingSnapshot(
                    creator_id=7,
                    video_id=901,
                    video_status="PROCESSING",
                    processing_status="PROCESSING",
                    retry_count=2,
                    lease_expire_at="2026-08-20 09:00:00",
                    error_summary="callback timeout; mock demo only",
                    updated_at="2026-08-20 09:01:00",
                    trace_id=trace_id,
                )
            ]
        )
        selected_model = model or FakeStructuredFlowPilotModel()
        async with open_workflow_runtime(
            repo,
            gateway,
            checkpoint_path=checkpoint_path,
            handler_actor=Actor("flowpilot-handler", Role.HANDLER),
            service_actor=Actor("flowpilot-action-executor", Role.SERVICE),
            model=selected_model,
        ) as runtime:
            app = build_app(
                pool,
                action_runner=runner,
                ticket_workflow=runtime.ticket_workflow,
                approval_workflow=runtime.approval_workflow,
            )
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://flowpilot-demo") as client:
                ticket_response = await client.post(
                    "/api/tickets",
                    json={"title": "Video processing stalled", "description": "Mock SW lease expired", "priority": 4},
                    headers=_SUBMITTER,
                )
                _require_success(ticket_response, "创建工单")
                ticket = ticket_response.json()
                thread_id = f"demo-{ticket['id']}"

                start_response = await client.post(
                    f"/api/workflows/tickets/{ticket['id']}/start",
                    json={"creator_id": 7, "video_id": 901, "trace_id": trace_id, "thread_id": thread_id},
                    headers={**_HANDLER, "X-Trace-Id": trace_id},
                )
                _require_success(start_response, "启动 Agent 工作流")
                started = start_response.json()

                approval_response = await client.post(
                    f"/api/workflows/proposals/{started['proposal']['id']}/approvals",
                    json={"decision": "approved", "thread_id": thread_id, "note": "Mock Demo 人工确认"},
                    headers=_APPROVER,
                )
                _require_success(approval_response, "审批并恢复工作流")
                approved = approval_response.json()

                final_ticket_response = await client.get(f"/api/tickets/{ticket['id']}", headers=_ADMIN)
                _require_success(final_ticket_response, "读取最终工单")
                evidence_response = await client.get(f"/api/tickets/{ticket['id']}/evidence", headers=_ADMIN)
                _require_success(evidence_response, "读取 Evidence")
                audit_response = await client.get(f"/api/audit/ticket/{ticket['id']}", headers=_ADMIN)
                _require_success(audit_response, "读取审计记录")

        return {
            "mode": (
                "mock-no-key"
                if isinstance(selected_model, FakeStructuredFlowPilotModel)
                else "mock-external-systems-real-model"
            ),
            "ticket": final_ticket_response.json(),
            "proposal": started["proposal"],
            "agent_run": started["agent_run"],
            "execution": approved["execution"],
            "trace_id": trace_id,
            "graph_steps_before_approval": started["steps"],
            "graph_steps_after_approval": approved["steps"],
            "evidence_count": len(evidence_response.json()),
            "ticket_audit_actions": [item["action"] for item in audit_response.json()],
            "mock_business_operations": runner.business.operations,
        }
    finally:
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 FlowPilot 主场景（默认不调用 LLM/SW）")
    parser.add_argument("--database-url", default=os.environ.get("FLOWPILOT_DATABASE_URL", ""))
    parser.add_argument("--checkpoint-path", default="")
    parser.add_argument("--trace-id", default="trace-demo-mock-1")
    parser.add_argument(
        "--skip-schema-init", action="store_true", help="已初始化 docker/postgres/init.sql 时跳过幂等 Schema 初始化"
    )
    parser.add_argument(
        "--structured-model-from-env",
        action="store_true",
        help="按 FLOWPILOT_STRUCTURED_MODEL 加载真实模型；SW 与业务执行仍保持 Mock",
    )
    return parser


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    cleanup_checkpoint = not args.checkpoint_path
    checkpoint_path = args.checkpoint_path or str(Path(tempfile.gettempdir()) / "flowpilot-demo-checkpoint.sqlite")
    model = structured_model_from_env() if args.structured_model_from_env else None
    if args.structured_model_from_env and model is None:
        raise ValueError("--structured-model-from-env 需要 FLOWPILOT_STRUCTURED_MODEL=qwen 或 fake")
    try:
        return await run_demo(
            database_url=args.database_url,
            checkpoint_path=checkpoint_path,
            trace_id=args.trace_id,
            initialize_schema=not args.skip_schema_init,
            model=model,
        )
    finally:
        if cleanup_checkpoint:
            Path(checkpoint_path).unlink(missing_ok=True)


def main() -> None:
    args = _parser().parse_args()
    result = asyncio.run(_main_async(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
