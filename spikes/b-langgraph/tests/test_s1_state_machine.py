"""S1 确定性状态机：直接复用 shared.domain（无 LLM、无框架）。"""
from __future__ import annotations

import pytest

from shared.domain import (
    ActionProposal,
    Evidence,
    IllegalTransitionError,
    Ticket,
    TicketStatus,
)


@pytest.mark.scenario("S1")
def test_s1_legal_transitions() -> None:
    ticket = Ticket(id="T-1", title="pipeline stalled")
    for target in (
        TicketStatus.TRIAGED,
        TicketStatus.INVESTIGATING,
        TicketStatus.PROPOSED,
        TicketStatus.WAITING_APPROVAL,
    ):
        ticket.transition(target)
    assert ticket.status == TicketStatus.WAITING_APPROVAL


@pytest.mark.scenario("S1")
def test_s1_illegal_transitions() -> None:
    ticket = Ticket(id="T-1", title="pipeline stalled")
    with pytest.raises(IllegalTransitionError):
        ticket.transition(TicketStatus.RESOLVED)

    resolved = Ticket(id="T-2", title="done", status=TicketStatus.RESOLVED)
    with pytest.raises(IllegalTransitionError):
        resolved.transition(TicketStatus.PROPOSED)


@pytest.mark.scenario("S1")
def test_s1_json_roundtrip() -> None:
    ticket = Ticket(id="T-1", title="pipeline stalled", status=TicketStatus.WAITING_APPROVAL)
    ticket.evidence.append(
        Evidence(
            tool="get_ticket_status",
            source="ticket-mcp",
            data={"ticket_id": "T-1", "status": "INVESTIGATING"},
            collected_at="2026-08-16T00:00:00+00:00",
        )
    )
    ticket.proposal = ActionProposal(
        action="restart_pipeline",
        params={"ticket_id": "T-1"},
        evidence_tools=("get_ticket_status",),
        risk="high",
    ).to_dict()

    restored = Ticket.from_json(ticket.to_json())
    assert restored.to_dict() == ticket.to_dict()
    assert restored.status == TicketStatus.WAITING_APPROVAL
    assert restored.evidence[0].tool == "get_ticket_status"
    assert restored.proposal is not None and restored.proposal["risk"] == "high"
