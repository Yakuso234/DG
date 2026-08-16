"""S3 — persistent HITL recovery across two "processes" + MAF checkpoint/HITL probes."""

from __future__ import annotations

import pathlib

import pytest
from agent_framework import FileCheckpointStorage

from shared import domain
from a_maf import maf_workflow as mw
from a_maf import ticket_store
from a_maf.fake_model import TICKET_ID
from a_maf.ticket_flow import build_waiting_approval_ticket


@pytest.mark.s3
async def test_s3_persist_and_recover_approval_gate(tmp_path, monkeypatch) -> None:
    # Isolate persistence under the test's tmp dir (no cross-test residue).
    monkeypatch.setattr(ticket_store, "DATA_DIR", pathlib.Path(tmp_path))

    # --- Process 1: investigate, propose, persist, destroy runtime objects ---
    ticket1 = await build_waiting_approval_ticket()
    assert ticket1.status == domain.TicketStatus.WAITING_APPROVAL
    assert ticket1.proposal is not None
    assert ticket1.proposal["risk"] == "high"
    assert len(ticket1.evidence) == 1

    saved_path = ticket_store.save_ticket(ticket1)
    assert saved_path.exists()
    del ticket1  # simulate process death

    # --- Process 2: recover from persistence ---
    ticket2 = ticket_store.load_ticket(TICKET_ID)
    assert ticket2.status == domain.TicketStatus.WAITING_APPROVAL
    assert len(ticket2.evidence) == 1
    assert ticket2.evidence[0].tool == "get_ticket_status"

    # --- Unapproved execution must be blocked (high risk). ---
    with pytest.raises(domain.ApprovalRequiredError):
        domain.execute_proposal(ticket2)

    # --- Approve, then execute exactly once and resolve. ---
    ticket2.approval = "approved"
    ticket2.transition(domain.TicketStatus.EXECUTING)
    executed = domain.execute_proposal(ticket2)
    assert executed == ["restart_pipeline"]
    ticket2.transition(domain.TicketStatus.RESOLVED)
    assert ticket2.status == domain.TicketStatus.RESOLVED

    # --- Idempotency: replay must not execute the same step twice. ---
    domain.execute_proposal(ticket2)
    assert ticket2.executed == ["restart_pipeline"]
    assert len(ticket2.executed) == 1


@pytest.mark.s3
async def test_s3_maf_file_checkpoint_storage_cross_instance(tmp_path) -> None:
    """MAF framework-native persistence: FileCheckpointStorage round-trips
    executor state across a *fresh* workflow instance (ch18 pattern)."""
    ckpt_dir = pathlib.Path(tmp_path) / "checkpoints"

    storage1 = FileCheckpointStorage(str(ckpt_dir))
    expected = await mw.run_checkpoint_workflow(
        storage1, seed="NEW", next_status="WAITING_APPROVAL"
    )
    assert expected == "WAITING_APPROVAL"
    assert list(ckpt_dir.iterdir()), "expected checkpoint files on disk"

    # Fresh storage + fresh workflow (different seed) => process 2.
    storage2 = FileCheckpointStorage(str(ckpt_dir))
    checkpoints = await storage2.list_checkpoints(workflow_name=mw.CHECKPOINT_WORKFLOW)
    assert checkpoints
    checkpoints.sort(key=lambda cp: cp.timestamp)
    first = checkpoints[0]

    replayed = await mw.resume_checkpoint_workflow(
        storage2, first.checkpoint_id, resume_seed="WRONG"
    )
    assert replayed == expected


@pytest.mark.s3
async def test_s3_maf_hitl_request_info_pause_and_resume() -> None:
    """MAF framework-native HITL: request_info pauses, resume with a canned answer."""
    result = await mw.run_hitl_with_response("approve restart_pipeline?", "approved")
    assert result == "approval=approved"
