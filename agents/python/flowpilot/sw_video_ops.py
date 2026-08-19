"""SW 视频处理运维的只读 HTTP 合同与 Evidence 归一。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from flowpilot.domain.models import Evidence, utc_now_iso


class SwVideoOpsError(RuntimeError):
    pass


class SwVideoOpsAuthError(SwVideoOpsError):
    pass


class SwVideoOpsNotFoundError(SwVideoOpsError):
    pass


class SwVideoOpsUpstreamError(SwVideoOpsError):
    pass


@dataclass(frozen=True)
class VideoProcessingSnapshot:
    creator_id: int
    video_id: int
    video_status: str
    processing_status: str | None
    retry_count: int | None
    lease_expire_at: str | None
    error_summary: str | None
    updated_at: str | None
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "creator_id": self.creator_id,
            "video_id": self.video_id,
            "video_status": self.video_status,
            "processing_status": self.processing_status,
            "retry_count": self.retry_count,
            "lease_expire_at": self.lease_expire_at,
            "error_summary": self.error_summary,
            "updated_at": self.updated_at,
            "trace_id": self.trace_id,
            "source_system": "sw-video-service",
        }


class SwVideoOpsGateway(Protocol):
    async def get_video_processing_status(
        self, *, creator_id: int, video_id: int, trace_id: str
    ) -> VideoProcessingSnapshot: ...

    async def get_processing_operations_overview(self, *, trace_id: str) -> dict[str, Any]: ...


class SwVideoOpsHttpGateway:
    """只读 SW 私有 HTTP 客户端：不允许没有服务身份的调用。"""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        service_name: str = "flowpilot",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not service_token.strip():
            raise SwVideoOpsAuthError("缺少 SW_VIDEO_SERVICE_TOKEN，拒绝无身份 SW 调用")
        self._base_url, self._service_token, self._service_name = base_url.rstrip("/"), service_token, service_name
        self._client, self._owns_client = client or httpx.AsyncClient(timeout=5.0), client is None

    @classmethod
    def from_env(cls) -> SwVideoOpsHttpGateway:
        base_url = os.environ.get("SW_VIDEO_BASE_URL", "").strip()
        if not base_url:
            raise SwVideoOpsError("缺少 SW_VIDEO_BASE_URL，不能调用 SW 私有接口")
        return cls(
            base_url=base_url,
            service_token=os.environ.get("SW_VIDEO_SERVICE_TOKEN", ""),
            service_name=os.environ.get("SW_VIDEO_SERVICE_NAME", "flowpilot"),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self, trace_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._service_token}",
            "X-FlowPilot-Service": self._service_name,
            "X-Trace-Id": trace_id,
        }

    async def _get(self, path: str, trace_id: str) -> dict[str, Any]:
        try:
            response = await self._client.get(f"{self._base_url}{path}", headers=self._headers(trace_id))
        except httpx.TimeoutException as exc:
            raise SwVideoOpsUpstreamError(f"SW 请求超时: {path}") from exc
        except httpx.HTTPError as exc:
            raise SwVideoOpsUpstreamError(f"SW 请求失败: {path}") from exc
        if response.status_code in (401, 403):
            raise SwVideoOpsAuthError(f"SW 拒绝服务身份（status={response.status_code}）")
        if response.status_code == 404:
            raise SwVideoOpsNotFoundError(f"SW 资源不存在或不可访问: {path}")
        if response.is_error:
            raise SwVideoOpsUpstreamError(f"SW 返回 HTTP {response.status_code}: {path}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SwVideoOpsUpstreamError("SW 返回非 JSON 响应") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise SwVideoOpsUpstreamError("SW 返回不符合 Result<data> 合同的响应")
        return payload["data"]

    async def get_video_processing_status(
        self, *, creator_id: int, video_id: int, trace_id: str
    ) -> VideoProcessingSnapshot:
        data = await self._get(f"/video/api/private/creator/{creator_id}/processing/{video_id}", trace_id)
        if data.get("videoId") != video_id or not isinstance(data.get("videoStatus"), str):
            raise SwVideoOpsUpstreamError("SW 视频状态响应缺少有效 videoId/videoStatus")
        error = data.get("errorMessage")
        return VideoProcessingSnapshot(
            creator_id,
            video_id,
            data["videoStatus"],
            data.get("processingStatus"),
            data.get("retryCount"),
            data.get("leaseExpireAt"),
            error[:512] if isinstance(error, str) else None,
            data.get("updatedAt"),
            trace_id,
        )

    async def get_processing_operations_overview(self, *, trace_id: str) -> dict[str, Any]:
        data = await self._get("/video/api/private/processing/operations/overview", trace_id)
        required = ("reviewQueueMessages", "deadLetterQueueMessages", "processingTaskCount", "failedTaskCount")
        if not all(isinstance(data.get(key), int) for key in required):
            raise SwVideoOpsUpstreamError("SW 运维概览缺少必需计数字段")
        return {
            "review_queue_messages": data["reviewQueueMessages"],
            "dead_letter_queue_messages": data["deadLetterQueueMessages"],
            "processing_task_count": data["processingTaskCount"],
            "failed_task_count": data["failedTaskCount"],
            "trace_id": trace_id,
            "source_system": "sw-video-service",
        }


class MockSwVideoOpsGateway:
    def __init__(self, snapshots: list[VideoProcessingSnapshot] | None = None) -> None:
        self._snapshots = {(item.creator_id, item.video_id): item for item in snapshots or []}
        self.calls: list[dict[str, Any]] = []

    async def get_video_processing_status(
        self, *, creator_id: int, video_id: int, trace_id: str
    ) -> VideoProcessingSnapshot:
        self.calls.append({"tool": "get_video_processing_status", "trace_id": trace_id})
        item = self._snapshots.get((creator_id, video_id))
        if item is None:
            raise SwVideoOpsNotFoundError(f"Mock 中不存在 creator={creator_id}, video={video_id}")
        return VideoProcessingSnapshot(
            creator_id,
            video_id,
            item.video_status,
            item.processing_status,
            item.retry_count,
            item.lease_expire_at,
            item.error_summary,
            item.updated_at,
            trace_id,
        )

    async def get_processing_operations_overview(self, *, trace_id: str) -> dict[str, Any]:
        self.calls.append({"tool": "get_processing_operations_overview", "trace_id": trace_id})
        return {
            "review_queue_messages": 0,
            "dead_letter_queue_messages": 0,
            "processing_task_count": len(self._snapshots),
            "failed_task_count": sum(item.processing_status == "FAILED" for item in self._snapshots.values()),
            "trace_id": trace_id,
            "source_system": "mock-sw-video-ops",
        }


def status_to_evidence(*, ticket_id: str, snapshot: VideoProcessingSnapshot) -> Evidence:
    return Evidence(
        id=f"sw-video-status:{snapshot.creator_id}:{snapshot.video_id}:{snapshot.trace_id}",
        ticket_id=ticket_id,
        tool="get_video_processing_status",
        source="sw-video-ops-mcp",
        data=snapshot.to_dict(),
        collected_at=utc_now_iso(),
    )
