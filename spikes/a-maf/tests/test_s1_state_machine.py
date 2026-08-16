"""S1 — deterministic state machine + JSON round-trip (shared domain, no LLM)."""

from __future__ import annotations

import pytest

from shared import domain

LEGAL_PATH = [
    domain.TicketStatus.TRIAGED,
    domain.TicketStatus.INVESTIGATING,
    domain.TicketStatus.PROPOSED,
    domain.TicketStatus.WAITING_APPROVAL,
]


def _new_ticket() -> domain.Ticket:
    return domain.Ticket(id="T-1", title="s1 ticket")


@pytest.mark.s1
def test_s1_legal_transitions_succeed() -> None:
    ticket = _new_ticket()
    for target in LEGAL_PATH:
        ticket.transition(target)
    assert ticket.status == domain.TicketStatus.WAITING_APPROVAL


@pytest.mark.s1
def test_s1_new_to_resolved_is_illegal() -> None:
    ticket = _new_ticket()
    with pytest.raises(domain.IllegalTransitionError):
        ticket.transition(domain.TicketStatus.RESOLVED)


@pytest.mark.s1
def test_s1_resolved_to_proposed_is_illegal() -> None:
    ticket = _new_ticket()
    for target in [
        domain.TicketStatus.TRIAGED,
        domain.TicketStatus.INVESTIGATING,
        domain.TicketStatus.PROPOSED,
        domain.TicketStatus.WAITING_APPROVAL,
        domain.TicketStatus.EXECUTING,
        domain.TicketStatus.RESOLVED,
    ]:
        ticket.transition(target)
    assert ticket.status == domain.TicketStatus.RESOLVED
    with pytest.raises(domain.IllegalTransitionError):
        ticket.transition(domain.TicketStatus.PROPOSED)


@pytest.mark.s1
def test_s1_json_roundtrip_preserves_fields() -> None:
    ticket = _new_ticket()
    for target in LEGAL_PATH:
        ticket.transition(target)
    ticket.evidence.append(
        domain.Evidence(
            tool="get_ticket_status",
            source="ticket-mcp",
            data={"ticket_id": "T-1001", "status": "INVESTIGATING"},
            collected_at=domain.utc_now_iso(),
        )
    )
    ticket.proposal = domain.ActionProposal(
        action="restart_pipeline",
        params={"ticket_id": "T-1001"},
        evidence_tools=("get_ticket_status",),
        risk="high",
    ).to_dict()
    ticket.approval = None

    restored = domain.Ticket.from_json(ticket.to_json())
    assert restored.to_dict() == ticket.to_dict()
    assert restored.status == domain.TicketStatus.WAITING_APPROVAL
    assert len(restored.evidence) == 1
    assert restored.evidence[0].tool == "get_ticket_status"
    assert restored.proposal is not None
    assert restored.proposal["action"] == "restart_pipeline"
