"""FlowPilot 工作流运行时：共享 graph/checkpointer，装配启动与审批服务。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from flowpilot.agent_graph import build_graph
from flowpilot.approval_workflow import ApprovalWorkflowRepository, ApprovalWorkflowService
from flowpilot.domain.rbac import Actor
from flowpilot.structured_model import StructuredFlowPilotModel
from flowpilot.sw_video_ops import SwVideoOpsGateway
from flowpilot.ticket_workflow import TicketWorkflowService


@dataclass(frozen=True)
class WorkflowRuntime:
    ticket_workflow: TicketWorkflowService
    approval_workflow: ApprovalWorkflowService


@asynccontextmanager
async def open_workflow_runtime(
    repo: ApprovalWorkflowRepository,
    gateway: SwVideoOpsGateway,
    *,
    checkpoint_path: str,
    handler_actor: Actor,
    service_actor: Actor,
    model: StructuredFlowPilotModel | None = None,
) -> AsyncIterator[WorkflowRuntime]:
    """打开 SQLite checkpoint，并让启动/恢复服务共享同一个已编译图。"""
    if not checkpoint_path.strip():
        raise ValueError("checkpoint_path 不能为空")
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(gateway, checkpointer=checkpointer, require_approval=True, model=model)
        yield WorkflowRuntime(
            ticket_workflow=TicketWorkflowService(repo, graph, handler_actor=handler_actor),
            approval_workflow=ApprovalWorkflowService(
                repo,
                graph,
                service_actor=service_actor,
                escalation_actor=handler_actor,
            ),
        )
