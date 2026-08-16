"""官方 a2a-sdk：内存 transport 完成 AgentCard 获取 + message:send 往返。

服务器侧用官方 DefaultRequestHandler + InMemoryTaskStore；客户端侧实现官方
ClientTransport 接口的内存实现（零 HTTP），把请求直连到 DefaultRequestHandler
—— 这是 a2a-sdk 测试套件同款的 InMemory 模式。

S5b（HTTP 跨进程）另提供 build_http_app()，用官方 create_jsonrpc_routes 把同一
Agent 暴露为 Starlette app，再用官方 ClientFactory.create_from_url 做往返。
"""
from __future__ import annotations

import json
from typing import Any

from google.protobuf import json_format

from a2a.client.base_client import BaseClient
from a2a.client.client import ClientConfig
from a2a.client.transports.base import ClientTransport
from a2a.helpers import new_data_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.types.a2a_pb2 import (
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    SendMessageConfiguration,
    StreamResponse,
    SubscribeToTaskRequest,
    TaskPushNotificationConfig,
)

AGENT_NAME = "b-langgraph-ticket-agent"
DEFAULT_URL = "http://localhost:8080"


def build_agent_card(url: str = DEFAULT_URL) -> AgentCard:
    """构建 AgentCard（官方 protobuf 类型）。"""
    return AgentCard(
        name=AGENT_NAME,
        description="FlowPilot ticket-resolution agent (SPIKE-001 B: LangGraph + a2a-sdk)",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text"],
        default_output_modes=["text", "application/json"],
        skills=[
            AgentSkill(
                id="ticket_triage",
                name="Ticket triage",
                description="Investigate a ticket and propose a high-risk remediation",
            )
        ],
    )


class TicketA2AExecutor(AgentExecutor):
    """返回结构化（可 JSON 解析）响应的最小 Agent。"""

    async def execute(self, context: RequestContext, event_queue: Any) -> None:
        user_input = context.get_user_input()
        structured = {
            "agent": AGENT_NAME,
            "reply_to": user_input,
            "action": "restart_pipeline",
            "ticket_id": "T-1001",
            "risk": "high",
            "status": "proposed",
        }
        message = new_data_message(
            structured,
            media_type="application/json",
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(message)

    async def cancel(self, context: RequestContext, event_queue: Any) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id or "",
                context_id=context.context_id or "",
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )


def build_request_handler(card: AgentCard | None = None) -> DefaultRequestHandler:
    """构建服务器侧 DefaultRequestHandler（同一 Agent，供内存/HTTP 复用）。"""
    card = card or build_agent_card()
    return DefaultRequestHandler(
        agent_executor=TicketA2AExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )


class InMemoryClientTransport(ClientTransport):
    """官方 ClientTransport 接口的内存实现：请求直连 DefaultRequestHandler。"""

    def __init__(self, handler: DefaultRequestHandler, card: AgentCard) -> None:
        self._handler = handler
        self._card = card

    async def send_message(
        self, request: SendMessageRequest, *, context: Any = None
    ) -> SendMessageResponse:
        result = await self._handler.on_message_send(request, ServerCallContext())
        resp = SendMessageResponse()
        if isinstance(result, Message):
            resp.message.CopyFrom(result)
        else:
            resp.task.CopyFrom(result)
        return resp

    async def send_message_streaming(
        self, request: SendMessageRequest, *, context: Any = None
    ) -> Any:
        raise NotImplementedError("S5a 使用非流式内存 transport")

    async def get_task(self, request: GetTaskRequest, *, context: Any = None) -> Task:
        task = await self._handler.on_get_task(request, ServerCallContext())
        if task is None:
            raise RuntimeError("task not found")
        return task

    async def get_extended_agent_card(
        self, request: GetExtendedAgentCardRequest, *, context: Any = None
    ) -> AgentCard:
        return self._card

    async def close(self) -> None:
        return None

    # 其余抽象方法：S5a 不涉及，显式 NotImplementedError。
    async def list_tasks(self, request: ListTasksRequest, *, context: Any = None) -> ListTasksResponse:
        raise NotImplementedError

    async def cancel_task(self, request: CancelTaskRequest, *, context: Any = None) -> Task:
        raise NotImplementedError

    async def create_task_push_notification_config(
        self, request: TaskPushNotificationConfig, *, context: Any = None
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def get_task_push_notification_config(
        self, request: GetTaskPushNotificationConfigRequest, *, context: Any = None
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def list_task_push_notification_configs(
        self, request: ListTaskPushNotificationConfigsRequest, *, context: Any = None
    ) -> ListTaskPushNotificationConfigsResponse:
        raise NotImplementedError

    async def delete_task_push_notification_config(
        self, request: DeleteTaskPushNotificationConfigRequest, *, context: Any = None
    ) -> None:
        raise NotImplementedError

    async def subscribe(
        self, request: SubscribeToTaskRequest, *, context: Any = None
    ) -> Any:
        raise NotImplementedError


def new_user_message(text: str) -> Message:
    """构造 ROLE_USER 文本消息。"""
    from a2a.helpers import new_message

    return new_message(parts=[new_text_part(text)], role=Role.ROLE_USER)


def send_message_in_memory(text: str) -> dict[str, Any]:
    """内存 transport 完整往返，返回可 JSON 解析的结构化 dict。"""
    card = build_agent_card()
    handler = build_request_handler(card)

    async def _run() -> dict[str, Any]:
        transport = InMemoryClientTransport(handler, card)
        client = BaseClient(card, ClientConfig(streaming=False), transport, [])
        try:
            request = SendMessageRequest(
                message=new_user_message(text),
                configuration=SendMessageConfiguration(),
            )
            responses = [sr async for sr in client.send_message(request)]
        finally:
            await client.close()

        assert len(responses) == 1
        sr: StreamResponse = responses[0]
        assert sr.HasField("message"), "expected a Message response"
        parts = sr.message.parts
        data_parts = [json_format.MessageToDict(p.data) for p in parts if p.HasField("data")]
        assert data_parts, "no structured data part in response"
        # 证明可 JSON 往返解析。
        return json.loads(json.dumps(data_parts[0]))

    import asyncio

    return asyncio.run(_run())


def build_http_app(card: AgentCard | None = None) -> Any:
    """S5b：把同一 Agent 以 HTTP(JSON-RPC) 暴露为 Starlette app。"""
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    card = card or build_agent_card()
    handler = build_request_handler(card)

    async def card_endpoint(request: Any) -> JSONResponse:
        return JSONResponse(json_format.MessageToDict(card))

    routes = create_jsonrpc_routes(handler, "/") + [
        Route("/.well-known/agent-card.json", endpoint=card_endpoint, methods=["GET"]),
    ]
    return Starlette(routes=routes)
