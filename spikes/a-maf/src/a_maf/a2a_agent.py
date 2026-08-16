"""A2A boundary: AgentCard fetch + message:send round-trip over an in-memory
transport built on the official ``a2a-sdk`` (no network).

The a2a-sdk 0.3.23 ships HTTP/gRPC/JSON-RPC transports but no in-memory one,
so this module implements ``InMemoryTransport(ClientTransport)`` — the SDK's
documented transport extension point — and bridges it directly to an
in-process ``RequestHandler`` (the same server logic the SDK's HTTP apps use).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from a2a.client.base_client import BaseClient
from a2a.client.client import ClientConfig
from a2a.client.transports.base import ClientTransport
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue, InMemoryQueueManager
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    GetTaskPushNotificationConfigParams,
    Message,
    MessageSendParams,
    Part,
    Role,
    Task,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TextPart,
    TransportProtocol,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

AGENT_NAME = "ticket-status-agent"
AGENT_URL = "mem://ticket-status-agent"

# Deterministic status table (mirrors the MCP read tool).
_STATUS: dict[str, str] = {"T-1001": "INVESTIGATING"}


class TicketStatusExecutor(AgentExecutor):
    """Minimal agent: echoes the queried ticket status as a structured Message."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = (context.get_user_input() or "").strip()
        ticket_id = text or "T-1001"
        payload = {
            "ticket_id": ticket_id,
            "status": _STATUS.get(ticket_id, "UNKNOWN"),
        }
        await event_queue.enqueue_event(
            Message(
                messageId=str(uuid.uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=json.dumps(payload)))],
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None


def build_agent_card(url: str = AGENT_URL) -> AgentCard:
    """Build the A2A AgentCard served by the transport.

    ``url`` defaults to the in-memory address; S5b passes the HTTP URL.
    """
    return AgentCard(
        name=AGENT_NAME,
        description="A2A agent returning deterministic ticket status.",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[],
        preferredTransport=TransportProtocol.jsonrpc,
        additionalInterfaces=[
            AgentInterface(transport=TransportProtocol.jsonrpc, url=url)
        ],
    )


def build_handler() -> DefaultRequestHandler:
    """Wire the SDK server-side request handler (in-memory stores)."""
    return DefaultRequestHandler(
        agent_executor=TicketStatusExecutor(),
        task_store=InMemoryTaskStore(),
        queue_manager=InMemoryQueueManager(),
    )


class InMemoryTransport(ClientTransport):
    """A2A client transport that calls the SDK request handler in-process."""

    def __init__(self, card: AgentCard, handler: DefaultRequestHandler) -> None:
        self._card = card
        self._handler = handler

    async def get_card(self, *, context=None, extensions=None, signature_verifier=None) -> AgentCard:
        return self._card

    async def send_message(self, request: MessageSendParams, *, context=None, extensions=None) -> Task | Message:
        return await self._handler.on_message_send(request, context=None)

    async def send_message_streaming(
        self, request: MessageSendParams, *, context=None, extensions=None
    ) -> AsyncGenerator[Message | Task | Any, None]:
        async for event in self._handler.on_message_send_stream(request, context=None):
            yield event

    async def get_task(self, request: TaskQueryParams, *, context=None, extensions=None) -> Task:
        task = await self._handler.on_get_task(request, context=None)
        if task is None:
            raise ServerError(error=UnsupportedOperationError())
        return task

    async def cancel_task(self, request: TaskIdParams, *, context=None, extensions=None) -> Task:
        task = await self._handler.on_cancel_task(request, context=None)
        if task is None:
            raise ServerError(error=UnsupportedOperationError())
        return task

    async def set_task_callback(self, request: TaskPushNotificationConfig, *, context=None, extensions=None) -> TaskPushNotificationConfig:
        return await self._handler.on_set_task_push_notification_config(request, context=None)

    async def get_task_callback(self, request: GetTaskPushNotificationConfigParams, *, context=None, extensions=None) -> TaskPushNotificationConfig:
        return await self._handler.on_get_task_push_notification_config(request, context=None)

    async def resubscribe(self, request: TaskIdParams, *, context=None, extensions=None) -> AsyncGenerator[Any, None]:
        raise ServerError(error=UnsupportedOperationError())
        yield  # pragma: no cover

    async def close(self) -> None:
        return None


def build_client() -> tuple[BaseClient, AgentCard]:
    """Build an a2a-sdk ``BaseClient`` over the in-memory transport."""
    card = build_agent_card()
    handler = build_handler()
    transport = InMemoryTransport(card, handler)
    config = ClientConfig(streaming=False)
    client = BaseClient(card, config, transport, [], [])
    return client, card


async def run_roundtrip(query: str) -> dict[str, Any]:
    """Fetch the AgentCard, send a message, and return the structured reply.

    Returns a JSON-serializable dict describing the full exchange.
    """
    client, _ = build_client()
    card = await client.get_card()

    request = Message(
        messageId=str(uuid.uuid4()),
        role=Role.user,
        parts=[Part(root=TextPart(text=query))],
    )

    response: Any = None
    async for item in client.send_message(request):
        response = item
        break

    # Non-streaming path yields either a Message or a (Task, None) tuple.
    if isinstance(response, tuple):
        response = response[0]

    response_payload = json.loads(response.model_dump_json())
    return {
        "agent_card": json.loads(card.model_dump_json()),
        "request": query,
        "response": response_payload,
    }
