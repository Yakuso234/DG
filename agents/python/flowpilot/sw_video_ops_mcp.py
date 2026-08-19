"""`sw-video-ops-mcp`：只读 SW 视频处理工具，不暴露恢复或写操作。"""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from flowpilot.sw_video_ops import SwVideoOpsGateway, SwVideoOpsHttpGateway

mcp = FastMCP(
    "sw-video-ops-mcp",
    instructions="Read-only SW video processing operations; never execute recovery or write actions.",
    host="0.0.0.0",
)
_gateway: SwVideoOpsGateway | None = None


def _current_gateway() -> SwVideoOpsGateway:
    global _gateway
    if _gateway is None:
        _gateway = SwVideoOpsHttpGateway.from_env()
    return _gateway


def set_gateway_for_tests(gateway: SwVideoOpsGateway | None) -> None:
    global _gateway
    _gateway = gateway


def _trace_id(trace_id: str | None) -> str:
    return trace_id or f"fp-{uuid.uuid4().hex[:12]}"


@mcp.tool()
async def get_video_processing_status(
    creator_id: Annotated[int, "SW creator ID"],
    video_id: Annotated[int, "SW video ID"],
    trace_id: Annotated[str | None, "Optional cross-system TraceId"] = None,
) -> dict:
    """Read a creator-scoped SW processing snapshot."""
    return (
        await _current_gateway().get_video_processing_status(
            creator_id=creator_id, video_id=video_id, trace_id=_trace_id(trace_id)
        )
    ).to_dict()


@mcp.tool()
async def get_processing_operations_overview(
    trace_id: Annotated[str | None, "Optional cross-system TraceId"] = None,
) -> dict:
    """Read SW queue/task counters for investigation context."""
    return await _current_gateway().get_processing_operations_overview(trace_id=_trace_id(trace_id))


app = mcp.streamable_http_app()


def main() -> None:
    import uvicorn

    uvicorn.run("flowpilot.sw_video_ops_mcp:app", host="0.0.0.0", port=int(os.environ.get("PORT", "9010")))
