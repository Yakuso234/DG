"""S2 MCP 读工具：官方 mcp SDK 内存 transport，Fake Model 驱动一次工具调用。"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from b_langgraph.fake_model import FakeModel, TOOL_NAME
from b_langgraph.mcp_tools import MCP_SERVER_NAME, call_ticket_mcp_tool
from shared.domain import Evidence, Ticket, utc_now_iso


@pytest.mark.scenario("S2")
def test_s2_fake_model_drives_mcp_read_tool_to_evidence() -> None:
    model = FakeModel()
    tool_call = model.next()
    assert tool_call is not None
    assert tool_call.name == TOOL_NAME
    assert tool_call.arguments == {"ticket_id": "T-1001"}

    result = asyncio.run(call_ticket_mcp_tool(tool_call.name, tool_call.arguments))
    assert result.is_error is False
    data = result.structured_content
    assert data["ticket_id"] == "T-1001"

    evidence = Evidence(
        tool=TOOL_NAME,
        source=MCP_SERVER_NAME,
        data=data,
        collected_at=utc_now_iso(),
    )
    ticket = Ticket(id="T-1001", title="pipeline stalled")
    ticket.evidence.append(evidence)

    assert len(ticket.evidence) == 1
    e = ticket.evidence[0]
    assert e.tool == "get_ticket_status"
    assert e.source == MCP_SERVER_NAME
    assert e.data["status"] == "INVESTIGATING"

    # collected_at 必须是 UTC ISO 8601，可被解析。
    parsed = datetime.fromisoformat(e.collected_at)
    assert parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


@pytest.mark.scenario("S2")
def test_s2_invalid_ticket_id_returns_structured_error() -> None:
    result = asyncio.run(
        call_ticket_mcp_tool(TOOL_NAME, {"ticket_id": "NOPE-999"})
    )
    assert result.is_error is True
    err = result.structured_content
    assert err and isinstance(err, dict)
    assert err.get("error", {}).get("code") == "TICKET_NOT_FOUND"

    text = str(err)
    assert text.strip() != ""
    assert "Traceback" not in text
    assert "File \"" not in text
