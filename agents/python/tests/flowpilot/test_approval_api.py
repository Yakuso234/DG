from __future__ import annotations

from typing import Any

import httpx

from flowpilot.api.main import build_app
from flowpilot.approval_workflow import ApprovalWorkflowResult
from flowpilot.domain.models import Approval, ExecutionRecord, utc_now_iso
from flowpilot.domain.status import TicketStatus

APPROVER_HEADERS = {"x-user-id": "u-approver", "x-user-role": "approver"}


class FakeApprovalWorkflow:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def decide(self, actor, proposal_id, decision, config, *, modified_params=None, note=""):
        self.calls.append(
            {
                "actor": actor,
                "proposal_id": proposal_id,
                "decision": decision,
                "config": config,
                "modified_params": modified_params,
                "note": note,
            }
        )
        approval = Approval(
            id="approval-1",
            proposal_id=proposal_id,
            ticket_id="ticket-1",
            approver=actor.id,
            decision=decision,
            modified_params=modified_params,
            note=note,
            decided_at=utc_now_iso(),
            version=1,
        )
        execution = ExecutionRecord(
            id="execution-1",
            proposal_id=proposal_id,
            ticket_id="ticket-1",
            idempotency_key=f"{proposal_id}:restart_pipeline",
            status="succeeded",
            attempts=1,
            result={"ok": True},
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
        )
        return ApprovalWorkflowResult(approval, {"steps": ["approval"]}, execution, TicketStatus.RESOLVED)


async def test_workflow_approval_route_delegates_thread_bound_decision() -> None:
    workflow = FakeApprovalWorkflow()
    transport = httpx.ASGITransport(app=build_app(approval_workflow=workflow))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/proposals/proposal-1/approvals",
            headers=APPROVER_HEADERS,
            json={"decision": "approved", "thread_id": "thread-1", "note": "已确认"},
        )

    assert response.status_code == 200
    assert response.json()["ticket_target"] == "RESOLVED"
    assert workflow.calls[0]["config"] == {"configurable": {"thread_id": "thread-1"}}
    assert workflow.calls[0]["actor"].id == "u-approver"


async def test_workflow_approval_route_fails_closed_when_runtime_missing() -> None:
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/proposals/proposal-1/approvals",
            headers=APPROVER_HEADERS,
            json={"decision": "approved", "thread_id": "thread-1"},
        )

    assert response.status_code == 503
