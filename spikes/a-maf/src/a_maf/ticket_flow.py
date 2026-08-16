"""Deterministic ticket investigation pipeline shared by S2/S3/S4.

Builds a Ticket T-1001 through ``NEW -> TRIAGED -> INVESTIGATING -> PROPOSED
-> WAITING_APPROVAL``, collecting one MCP read-tool evidence entry and a
high-risk ``ActionProposal``.
"""

from __future__ import annotations

from shared import domain

from .mcp_server import run_read_flow


async def build_waiting_approval_ticket() -> domain.Ticket:
    """Run the full investigation and return a Ticket at WAITING_APPROVAL."""
    ticket, proposal = await run_read_flow()  # NEW + one evidence entry

    ticket.transition(domain.TicketStatus.TRIAGED)
    ticket.transition(domain.TicketStatus.INVESTIGATING)
    ticket.transition(domain.TicketStatus.PROPOSED)
    ticket.proposal = proposal.to_dict()
    ticket.transition(domain.TicketStatus.WAITING_APPROVAL)
    return ticket
