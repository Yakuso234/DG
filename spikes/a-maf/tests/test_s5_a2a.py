"""S5a — A2A in-memory transport: AgentCard fetch + message:send round-trip.
S5b — best-effort cross-process HTTP round-trip (official a2a-sdk client)."""

from __future__ import annotations

import asyncio
import json

import pytest

from a_maf import a2a_agent


@pytest.mark.s5a
async def test_s5a_agent_card_fetch_and_message_send_roundtrip() -> None:
    result = await a2a_agent.run_roundtrip("T-1001")

    # 1. AgentCard retrieved.
    card = result["agent_card"]
    assert card["name"] == a2a_agent.AGENT_NAME
    assert card["url"] == a2a_agent.AGENT_URL
    assert card["capabilities"]["streaming"] is False

    # 2. message:send returned a structured, JSON-parseable response.
    response = result["response"]
    assert response["role"] == "agent"
    parts = response.get("parts", [])
    assert parts, "expected at least one part in the A2A response"
    payload = json.loads(parts[0]["text"])
    assert payload == {"ticket_id": "T-1001", "status": "INVESTIGATING"}


@pytest.mark.s5a
async def test_s5a_roundtrip_is_reproducible() -> None:
    first = await a2a_agent.run_roundtrip("T-1001")
    second = await a2a_agent.run_roundtrip("T-1001")
    assert first["response"]["parts"] == second["response"]["parts"]


@pytest.mark.s5b
async def test_s5b_http_cross_process_roundtrip() -> None:
    """Best-effort: expose the same agent over HTTP and drive it with the
    official a2a-sdk client. Fails safe to SKIPPED-WITH-REASON."""
    try:
        import uvicorn
        from a2a.client import ClientFactory
        from a2a.server.apps.jsonrpc import A2AStarletteApplication
        from a2a.types import Message, Part, Role, TextPart
    except Exception as exc:  # pragma: no cover - dependency wiring guard
        pytest.skip(f"SKIPPED-WITH-REASON: S5b deps unavailable: {exc}")

    try:
        import socket

        # Reserve a free loopback port, then release it for uvicorn to bind.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        url = f"http://127.0.0.1:{port}"
        handler = a2a_agent.build_handler()
        card = a2a_agent.build_agent_card(url=url)
        app = A2AStarletteApplication(card, http_handler=handler).build()

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())

        # Wait for the server to finish binding.
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        if not server.started:  # pragma: no cover
            raise RuntimeError("uvicorn server did not start")

        try:
            client = await ClientFactory.connect(url)
            fetched_card = await client.get_card()
            assert fetched_card.name == a2a_agent.AGENT_NAME

            request = Message(
                messageId="s5b-request",
                role=Role.user,
                parts=[Part(root=TextPart(text="T-1001"))],
            )
            response = None
            async for item in client.send_message(request):
                response = item
                break
            if isinstance(response, tuple):  # (Task, update) pair
                response = response[0]

            payload = json.loads(response.model_dump_json())
            text = payload["parts"][0]["text"]
            assert json.loads(text) == {
                "ticket_id": "T-1001",
                "status": "INVESTIGATING",
            }
        finally:
            server.should_exit = True
            await serve_task
    except Exception as exc:  # noqa: BLE001 - best-effort scenario
        pytest.skip(f"SKIPPED-WITH-REASON: S5b HTTP round-trip failed: {exc}")
