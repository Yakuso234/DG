"""通过 MCP Streamable HTTP 调用 SW 视频运维只读工具。

Agent 图只依赖 ``SwVideoOpsGateway`` 协议；本适配器把真实 MCP 会话保留在
协议边界，避免让 Agent 节点直接拼接 HTTP 或解析 JSON-RPC 响应。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from flowpilot.sw_video_ops import (
    SwVideoOpsAuthError,
    SwVideoOpsError,
    SwVideoOpsNotFoundError,
    SwVideoOpsUpstreamError,
    VideoProcessingSnapshot,
)


class SwVideoOpsMcpGateway:
    """只读 MCP 客户端；每次工具调用独立协商会话并在退出时主动终止。"""

    def __init__(
        self,
        *,
        mcp_url: str,
        service_token: str,
        service_name: str = "flowpilot",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not mcp_url.strip():
            raise SwVideoOpsError("缺少 SW_VIDEO_MCP_URL，不能调用 SW MCP 服务")
        if not service_token.strip():
            raise SwVideoOpsAuthError("缺少 SW_VIDEO_SERVICE_TOKEN，拒绝无身份 MCP 调用")
        if not service_name.strip():
            raise SwVideoOpsAuthError("SW_VIDEO_SERVICE_NAME 不能为空")
        self._mcp_url = mcp_url.strip()
        self._service_token = service_token.strip()
        self._service_name = service_name.strip()
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            trust_env=False,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-FlowPilot-Service": self._service_name,
            },
        )
        self._owns_client = client is None

    @classmethod
    def from_env(cls) -> SwVideoOpsMcpGateway:
        return cls(
            mcp_url=os.environ.get("SW_VIDEO_MCP_URL", ""),
            service_token=os.environ.get("SW_VIDEO_SERVICE_TOKEN", ""),
            service_name=os.environ.get("SW_VIDEO_SERVICE_NAME", "flowpilot"),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            async with streamable_http_client(self._mcp_url, http_client=self._client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        except SwVideoOpsError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise SwVideoOpsAuthError(f"SW MCP 拒绝服务身份（status={exc.response.status_code}）") from exc
            if exc.response.status_code == 404:
                raise SwVideoOpsNotFoundError("SW MCP 端点不存在或不可访问") from exc
            raise SwVideoOpsUpstreamError(f"SW MCP 返回 HTTP {exc.response.status_code}: {name}") from exc
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            raise SwVideoOpsUpstreamError(f"SW MCP 工具调用失败: {name}") from exc

        if result.isError:
            text = " ".join(item.text for item in result.content if isinstance(getattr(item, "text", None), str))[:512]
            raise SwVideoOpsUpstreamError(f"SW MCP 工具返回错误: {name}: {text or '未提供详情'}")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        for item in result.content:
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise SwVideoOpsUpstreamError(f"SW MCP 工具未返回结构化对象: {name}")

    async def get_video_processing_status(
        self, *, creator_id: int, video_id: int, trace_id: str
    ) -> VideoProcessingSnapshot:
        data = await self._call_tool(
            "get_video_processing_status",
            {"creator_id": creator_id, "video_id": video_id, "trace_id": trace_id},
        )
        if data.get("creator_id") != creator_id or data.get("video_id") != video_id:
            raise SwVideoOpsNotFoundError("SW MCP 返回的业务对象与请求范围不一致")
        if data.get("trace_id") != trace_id:
            raise SwVideoOpsUpstreamError("SW MCP 返回的 TraceId 与请求不一致")
        if not isinstance(data.get("video_status"), str):
            raise SwVideoOpsUpstreamError("SW MCP 状态结果缺少有效 video_status")
        processing_status = data.get("processing_status")
        retry_count = data.get("retry_count")
        if processing_status is not None and not isinstance(processing_status, str):
            raise SwVideoOpsUpstreamError("SW MCP 状态结果 processing_status 类型非法")
        if isinstance(retry_count, bool) or (retry_count is not None and not isinstance(retry_count, int)):
            raise SwVideoOpsUpstreamError("SW MCP 状态结果 retry_count 类型非法")
        return VideoProcessingSnapshot(
            creator_id=creator_id,
            video_id=video_id,
            video_status=data["video_status"],
            processing_status=processing_status,
            retry_count=retry_count,
            lease_expire_at=data.get("lease_expire_at") if isinstance(data.get("lease_expire_at"), str) else None,
            error_summary=data.get("error_summary")[:512] if isinstance(data.get("error_summary"), str) else None,
            updated_at=data.get("updated_at") if isinstance(data.get("updated_at"), str) else None,
            trace_id=trace_id,
        )

    async def get_processing_operations_overview(self, *, trace_id: str) -> dict[str, Any]:
        data = await self._call_tool("get_processing_operations_overview", {"trace_id": trace_id})
        required = (
            "review_queue_messages",
            "dead_letter_queue_messages",
            "processing_task_count",
            "failed_task_count",
        )
        if data.get("trace_id") != trace_id or not all(
            isinstance(data.get(key), int) and not isinstance(data.get(key), bool) for key in required
        ):
            raise SwVideoOpsUpstreamError("SW MCP 运维概览不符合合同")
        return {
            **{key: data[key] for key in required},
            "trace_id": trace_id,
            "source_system": data.get("source_system", "sw-video-ops-mcp"),
        }
