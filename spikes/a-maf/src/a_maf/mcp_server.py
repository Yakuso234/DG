"""Minimal MCP read-only server (official ``mcp`` SDK, in-memory transport).

Exposes ``get_ticket_status(ticket_id)`` returning deterministic JSON. The
server runs over ``mcp.shared.memory`` (anyio memory streams) — no sockets,
no network.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session

from shared import domain

from .fake_model import TOOL_NAME, TICKET_ID, FakeModel, ToolCall

MCP_SERVER_NAME = "ticket-mcp"

# Deterministic read-only "database".
TICKET_STATUS_DB: dict[str, dict[str, Any]] = {
    TICKET_ID: {
        "ticket_id": TICKET_ID,
        "title": "order pipeline stuck",
        "status": "INVESTIGATING",
    },
}


def _text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str, extra: dict[str, Any]) -> types.CallToolResult:
    """Structured, stack-free error result (contract §5 S2)."""
    payload: dict[str, Any] = {"error": message, **extra}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=_text(payload))],
        isError=True,
    )


def build_server() -> Server:
    """Build the minimal in-memory MCP server with one read tool."""
    server = Server(MCP_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=TOOL_NAME,
                description="Return the current status of a ticket (read-only).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "string",
                            "description": "Ticket id, e.g. T-1001",
                        },
                    },
                    "required": ["ticket_id"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name != TOOL_NAME:
            return _error(f"unknown tool: {name}", {"tool": name})
        ticket_id = arguments.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            return _error("ticket_id is required", {"ticket_id": ticket_id})
        row = TICKET_STATUS_DB.get(ticket_id)
        if row is None:
            return _error(f"ticket not found: {ticket_id}", {"ticket_id": ticket_id})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=_text(row))],
            structuredContent=row,
            isError=False,
        )

    return server


async def call_read_tool(tool_call: ToolCall) -> dict[str, Any]:
    """Execute one read-tool call over an in-memory MCP session.

    Returns the normalized, JSON-decodable structured content, or raises
    ``RuntimeError`` when the server returns a structured error.
    """
    server = build_server()
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(tool_call.name, arguments=tool_call.arguments)
    if result.isError:
        text = "\n".join(
            c.text for c in result.content if isinstance(c, types.TextContent)
        )
        raise RuntimeError(f"MCP tool error: {text}")
    if result.structuredContent is not None:
        return dict(result.structuredContent)
    text = "\n".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    return json.loads(text) if text else {}


async def run_read_flow() -> tuple[domain.Ticket, domain.ActionProposal]:
    """Fake Model drives one read-tool call; result becomes Evidence (S2).

    Returns a fresh ``Ticket`` (status NEW, one evidence entry) plus the fixed
    ``ActionProposal`` produced by the Fake Model's second round.
    """
    model = FakeModel()
    tool_call = model.next()  # round 1
    assert isinstance(tool_call, ToolCall), "round 1 must be a tool call"
    data = await call_read_tool(tool_call)

    evidence = domain.Evidence(
        tool=TOOL_NAME,
        source=MCP_SERVER_NAME,
        data=data,
        collected_at=domain.utc_now_iso(),
    )
    ticket = domain.Ticket(id=TICKET_ID, title=str(data.get("title", "untitled")))
    ticket.evidence.append(evidence)

    proposal = model.next(tool_result=data)  # round 2
    assert isinstance(proposal, domain.ActionProposal), "round 2 must be a proposal"
    return ticket, proposal
