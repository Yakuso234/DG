from __future__ import annotations

import httpx
import pytest

from flowpilot.sw_video_ops import (
    MockSwVideoOpsGateway,
    SwVideoOpsAuthError,
    SwVideoOpsHttpGateway,
    SwVideoOpsNotFoundError,
    VideoProcessingSnapshot,
    status_to_evidence,
)
from flowpilot.sw_video_ops_mcp import (
    get_processing_operations_overview,
    get_video_processing_status,
    set_gateway_for_tests,
)


async def test_http_gateway_passes_service_identity_trace_and_private_path() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            path=request.url.path,
            authorization=request.headers["authorization"],
            service=request.headers["x-flowpilot-service"],
            trace=request.headers["x-trace-id"],
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "videoId": 9,
                    "videoStatus": "PROCESSING",
                    "processingStatus": "PROCESSING",
                    "retryCount": 2,
                    "leaseExpireAt": "2026-08-19 10:00:00",
                    "errorMessage": "callback timeout",
                    "updatedAt": "2026-08-19 09:00:00",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = SwVideoOpsHttpGateway(base_url="http://sw-video:8080", service_token="token-1", client=client)
    snapshot = await gateway.get_video_processing_status(creator_id=7, video_id=9, trace_id="trace-p2")
    await client.aclose()

    assert seen == {
        "path": "/video/api/private/creator/7/processing/9",
        "authorization": "Bearer token-1",
        "service": "flowpilot",
        "trace": "trace-p2",
    }
    assert snapshot.processing_status == "PROCESSING"
    assert snapshot.error_summary == "callback timeout"


async def test_http_gateway_rejects_missing_identity_and_not_found() -> None:
    with pytest.raises(SwVideoOpsAuthError):
        SwVideoOpsHttpGateway(base_url="http://sw-video", service_token="")

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    gateway = SwVideoOpsHttpGateway(base_url="http://sw-video", service_token="token", client=client)
    with pytest.raises(SwVideoOpsNotFoundError):
        await gateway.get_video_processing_status(creator_id=1, video_id=2, trace_id="t")
    await client.aclose()


async def test_mock_gateway_mcp_tools_and_evidence_normalization() -> None:
    mock = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-19 10:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    set_gateway_for_tests(mock)
    try:
        status = await get_video_processing_status(creator_id=7, video_id=9, trace_id="trace-9")
        overview = await get_processing_operations_overview(trace_id="trace-9")
    finally:
        set_gateway_for_tests(None)

    snapshot = VideoProcessingSnapshot(
        status["creator_id"],
        status["video_id"],
        status["video_status"],
        status["processing_status"],
        status["retry_count"],
        status["lease_expire_at"],
        status["error_summary"],
        status["updated_at"],
        status["trace_id"],
    )
    evidence = status_to_evidence(ticket_id="ticket-1", snapshot=snapshot)
    assert evidence.source == "sw-video-ops-mcp"
    assert evidence.data["source_system"] == "sw-video-service"
    assert overview["processing_task_count"] == 1
    assert [call["tool"] for call in mock.calls] == [
        "get_video_processing_status",
        "get_processing_operations_overview",
    ]
