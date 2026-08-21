from __future__ import annotations

from typing import Any

import httpx

from flowpilot.api.main import build_app
from flowpilot.domain.models import ActionProposal, Evidence, utc_now_iso
from flowpilot.domain.status import TicketStatus
from flowpilot.ticket_workflow import TicketWorkflowStartResult

HANDLER_HEADERS = {"x-user-id": "u-handler", "x-user-role": "handler"}


class FakeTicketWorkflow:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def start(self, **kwargs: Any) -> TicketWorkflowStartResult:
        self.calls.append(kwargs)
        evidence = Evidence("evidence-1", kwargs["ticket_id"], "status", "sw-video-ops-mcp", {}, utc_now_iso())
        proposal = ActionProposal(
            "proposal-1",
            kwargs["ticket_id"],
            "recover_expired_video_processing",
            {
                "ticket_id": kwargs["ticket_id"],
                "creator_id": kwargs["creator_id"],
                "video_id": kwargs["video_id"],
                "trace_id": kwargs["trace_id"],
            },
            [evidence.id],
            "high",
            "flowpilot-resolution-agent",
            utc_now_iso(),
        )
        return TicketWorkflowStartResult(
            kwargs["ticket_id"],
            kwargs["thread_id"],
            (evidence,),
            proposal,
            {"steps": ["triage", "investigation", "resolution", "risk_review"]},
        )


async def test_start_workflow_route_binds_business_and_trace_identifiers() -> None:
    workflow = FakeTicketWorkflow()
    transport = httpx.ASGITransport(app=build_app(ticket_workflow=workflow))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/tickets/ticket-1/start",
            headers={**HANDLER_HEADERS, "X-Trace-Id": "trace-1"},
            json={"creator_id": 7, "video_id": 9, "trace_id": "trace-1", "thread_id": "thread-1"},
        )

    assert response.status_code == 202
    assert response.json()["ticket_target"] == TicketStatus.WAITING_APPROVAL.value
    assert response.json()["trace_id"] == "trace-1"
    assert response.headers["X-Trace-Id"] == "trace-1"
    assert workflow.calls == [
        {"ticket_id": "ticket-1", "creator_id": 7, "video_id": 9, "trace_id": "trace-1", "thread_id": "thread-1"}
    ]


async def test_workflow_rejects_mismatched_request_and_business_trace_ids() -> None:
    transport = httpx.ASGITransport(app=build_app(ticket_workflow=FakeTicketWorkflow()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/tickets/ticket-1/start",
            headers={**HANDLER_HEADERS, "X-Trace-Id": "trace-header"},
            json={"creator_id": 7, "video_id": 9, "trace_id": "trace-body", "thread_id": "thread-1"},
        )

    assert response.status_code == 422
    assert "X-Trace-Id" in response.json()["detail"]


async def test_start_workflow_route_fails_closed_when_runtime_missing() -> None:
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/tickets/ticket-1/start",
            headers=HANDLER_HEADERS,
            json={"creator_id": 7, "video_id": 9, "trace_id": "trace-1", "thread_id": "thread-1"},
        )

    assert response.status_code == 503
