"""Application-layer file persistence for ``Ticket`` (shared to_json/from_json).

Used by S3 as the cross-"process" persistence boundary. Storage lives under
``spikes/a-maf/data/`` as one JSON file per ticket id.
"""

from __future__ import annotations

import pathlib

from shared import domain

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "data"


def ticket_path(ticket_id: str) -> pathlib.Path:
    return DATA_DIR / f"{ticket_id}.json"


def save_ticket(ticket: domain.Ticket) -> pathlib.Path:
    """Persist a ticket to disk and return the written path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = ticket_path(ticket.id)
    path.write_text(ticket.to_json(), encoding="utf-8")
    return path


def load_ticket(ticket_id: str) -> domain.Ticket:
    """Restore a ticket from disk."""
    path = ticket_path(ticket_id)
    if not path.exists():
        raise FileNotFoundError(f"no persisted ticket for {ticket_id}")
    return domain.Ticket.from_json(path.read_text(encoding="utf-8"))


def delete_ticket(ticket_id: str) -> None:
    path = ticket_path(ticket_id)
    if path.exists():
        path.unlink()
