"""S2 — official MCP SDK in-memory server + Fake-Model-driven read tool."""

from __future__ import annotations

from datetime import datetime

import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from a_maf.fake_model import FakeModel, TOOL_NAME, TICKET_ID, ToolCall
from a_maf.mcp_server import MCP_SERVER_NAME, build_server, run_read_flow


@pytest.mark.s2
async def test_s2_fake_model_drives_one_tool_call_and_stores_evidence() -> None:
    ticket, proposal = await run_read_flow()

    assert len(ticket.evidence) == 1
    evidence = ticket.evidence[0]
    assert evidence.tool == TOOL_NAME
    assert evidence.source == MCP_SERVER_NAME
    assert evidence.data["ticket_id"] == TICKET_ID
    assert evidence.data["status"] == "INVESTIGATING"

    # collected_at must be ISO-8601 UTC (offset +00:00 and tz-aware).
    parsed = datetime.fromisoformat(evidence.collected_at)
    assert evidence.collected_at.endswith("+00:00")
    assert parsed.tzinfo is not None

    # Round 2 produces the fixed high-risk proposal.
    assert proposal.action == "restart_pipeline"
    assert proposal.params == {"ticket_id": TICKET_ID}
    assert proposal.evidence_tools == (TOOL_NAME,)
    assert proposal.risk == "high"


@pytest.mark.s2
async def test_s2_illegal_ticket_id_returns_structured_error() -> None:
    server = build_server()
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            TOOL_NAME, arguments={"ticket_id": "NOPE-999"}
        )

    assert result.isError is True
    text = "\n".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    assert text  # non-empty
    assert "ticket not found" in text
    assert "Traceback" not in text  # no stack traces


@pytest.mark.s2
def test_s2_fake_model_rounds_are_deterministic() -> None:
    model = FakeModel()
    call = model.next()
    assert isinstance(call, ToolCall)
    assert call.name == TOOL_NAME
    assert call.arguments == {"ticket_id": TICKET_ID}

    proposal = model.next(tool_result={"ticket_id": TICKET_ID, "status": "INVESTIGATING"})
    assert proposal.action == "restart_pipeline"
    assert proposal.risk == "high"

    with pytest.raises(StopIteration):
        model.next()
