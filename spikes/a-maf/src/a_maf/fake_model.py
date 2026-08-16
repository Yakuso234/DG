"""Deterministic, network-free Fake Model — SPIKE-001 contract §4.

Two fixed rounds:

1. tool call ``get_ticket_status(ticket_id="T-1001")``
2. fixed ``ActionProposal(action="restart_pipeline", ..., risk="high")``, then stop

No HTTP/DNS, no environment-variable key reads, no real LLM client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared import domain

TOOL_NAME = "get_ticket_status"
TICKET_ID = "T-1001"


@dataclass(frozen=True)
class ToolCall:
    """A deterministic tool invocation emitted by the Fake Model."""

    name: str
    arguments: dict[str, Any]


class FakeModel:
    """Model substitute that replays the contract §4 script deterministically."""

    def __init__(self) -> None:
        self._round = 0

    @property
    def round(self) -> int:
        return self._round

    def next(self, tool_result: Any = None) -> ToolCall | domain.ActionProposal:
        """Advance one deterministic step.

        Round 1 ignores ``tool_result`` and emits the read-tool call.
        Round 2 receives the tool result and emits the fixed proposal.
        """
        self._round += 1
        if self._round == 1:
            return ToolCall(name=TOOL_NAME, arguments={"ticket_id": TICKET_ID})
        if self._round == 2:
            return domain.ActionProposal(
                action="restart_pipeline",
                params={"ticket_id": TICKET_ID},
                evidence_tools=(TOOL_NAME,),
                risk="high",
            )
        raise StopIteration("FakeModel completes after round 2")
