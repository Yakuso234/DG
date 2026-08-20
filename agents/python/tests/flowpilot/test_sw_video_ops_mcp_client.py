from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import uvicorn

from flowpilot.sw_video_ops import (
    MockSwVideoOpsGateway,
    SwVideoOpsError,
    VideoProcessingSnapshot,
    gateway_from_env,
)
from flowpilot.sw_video_ops_mcp import app, set_gateway_for_tests
from flowpilot.sw_video_ops_mcp_client import SwVideoOpsMcpGateway


@asynccontextmanager
async def _running_mcp_server(gateway: MockSwVideoOpsGateway) -> AsyncIterator[str]:
    """启动真实 loopback MCP HTTP 服务，验证协议而非进程内函数调用。"""
    set_gateway_for_tests(gateway)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started and server.servers:
                socket = next(iter(server.servers)).sockets[0]
                host, port = socket.getsockname()[:2]
                yield f"http://{host}:{port}/mcp"
                break
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("测试 MCP 服务未在 1 秒内启动")
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        set_gateway_for_tests(None)


async def test_mcp_gateway_reads_snapshot_and_overview_over_streamable_http() -> None:
    mock = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7,
                9,
                "PROCESSING",
                "PROCESSING",
                1,
                "2026-08-20 10:00:00",
                "callback timeout",
                "2026-08-20 09:00:00",
                "seed",
            )
        ]
    )
    async with _running_mcp_server(mock) as mcp_url:
        gateway = SwVideoOpsMcpGateway(mcp_url=mcp_url, service_token="test-service-token")
        try:
            snapshot = await gateway.get_video_processing_status(creator_id=7, video_id=9, trace_id="trace-mcp-1")
            overview = await gateway.get_processing_operations_overview(trace_id="trace-mcp-1")
        finally:
            await gateway.aclose()

    assert snapshot.creator_id == 7
    assert snapshot.video_id == 9
    assert snapshot.error_summary == "callback timeout"
    assert snapshot.trace_id == "trace-mcp-1"
    assert overview == {
        "review_queue_messages": 0,
        "dead_letter_queue_messages": 0,
        "processing_task_count": 1,
        "failed_task_count": 0,
        "trace_id": "trace-mcp-1",
        "source_system": "mock-sw-video-ops",
    }
    assert mock.calls == [
        {"tool": "get_video_processing_status", "trace_id": "trace-mcp-1"},
        {"tool": "get_processing_operations_overview", "trace_id": "trace-mcp-1"},
    ]


async def test_gateway_factory_selects_mcp_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLOWPILOT_SW_OPS_TRANSPORT", "mcp")
    monkeypatch.setenv("SW_VIDEO_MCP_URL", "http://127.0.0.1:9010/mcp")
    monkeypatch.setenv("SW_VIDEO_SERVICE_TOKEN", "test-service-token")

    gateway = gateway_from_env()
    try:
        assert isinstance(gateway, SwVideoOpsMcpGateway)
    finally:
        await gateway.aclose()


def test_gateway_factory_rejects_unknown_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLOWPILOT_SW_OPS_TRANSPORT", "grpc")

    with pytest.raises(SwVideoOpsError, match="direct-http 或 mcp"):
        gateway_from_env()
