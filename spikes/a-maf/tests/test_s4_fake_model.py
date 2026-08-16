"""S4 — Fake Model full chain with no network and no real LLM client."""

from __future__ import annotations

import pathlib
import socket

import pytest

from shared import domain
from a_maf import mcp_server, ticket_flow, ticket_store
from a_maf.fake_model import TICKET_ID, FakeModel


@pytest.mark.s4
async def test_s4_full_chain_runs_with_network_blocked(tmp_path, monkeypatch) -> None:
    """S2 + S3 flows must complete while any DNS/TCP attempt raises."""

    def _network_boom(*_args, **_kwargs):  # pragma: no cover - never expected
        raise AssertionError("network access attempted during Fake Model chain")

    monkeypatch.setattr(socket, "getaddrinfo", _network_boom)
    monkeypatch.setattr(socket, "create_connection", _network_boom)
    monkeypatch.setattr(ticket_store, "DATA_DIR", pathlib.Path(tmp_path))

    # S2 read flow (in-memory MCP).
    ticket, proposal = await mcp_server.run_read_flow()
    assert len(ticket.evidence) == 1
    assert proposal.risk == "high"

    # S3 investigation -> WAITING_APPROVAL -> persist -> recover -> execute.
    ticket1 = await ticket_flow.build_waiting_approval_ticket()
    ticket_store.save_ticket(ticket1)
    del ticket1

    ticket2 = ticket_store.load_ticket(TICKET_ID)
    assert ticket2.status == domain.TicketStatus.WAITING_APPROVAL
    with pytest.raises(domain.ApprovalRequiredError):
        domain.execute_proposal(ticket2)
    ticket2.approval = "approved"
    ticket2.transition(domain.TicketStatus.EXECUTING)
    domain.execute_proposal(ticket2)
    ticket2.transition(domain.TicketStatus.RESOLVED)
    assert ticket2.status == domain.TicketStatus.RESOLVED


@pytest.mark.s4
def test_s4_no_real_llm_client_constructed_in_glue() -> None:
    """Glue code must not reference any real provider LLM client."""
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "a_maf"
    banned = (
        "OpenAIChatClient",
        "AzureOpenAIChatClient",
        "AnthropicChatClient",
        "import openai",
        "import anthropic",
        "api_key",
        "OPENAI_API_KEY",
    )
    for path in sorted(src.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} references {token!r}"


@pytest.mark.s4
def test_s4_fake_model_is_pure_and_never_reads_env_keys(monkeypatch) -> None:
    """FakeModel is pure data: no os.environ access, no network imports."""
    model = FakeModel()
    call = model.next()
    assert call.name == "get_ticket_status"
    proposal = model.next(tool_result={"ticket_id": TICKET_ID})
    assert proposal.risk == "high"

    # Ensure the FakeModel module never touches the environment for keys.
    import a_maf.fake_model as fm

    src_text = pathlib.Path(fm.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in src_text
    assert "requests" not in src_text
    assert "httpx" not in src_text
