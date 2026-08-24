"""审批后的 SW 视频恢复动作适配器。

该模块刻意不实现 MCP Tool：Agent 只能提出结构化提案，写操作必须由
TicketRepo 在审批落库、幂等占位和审计开始事件完成后调用本适配器。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from flowpilot.action_runner import (
    ActionOutcomeUnknownError,
    ReconciliationOutcome,
    UnsupportedBusinessActionError,
)
from flowpilot.domain.executor import (
    SW_VIDEO_RECOVERY_ACTION,
    ParamValidationError,
    validate_params,
)
from flowpilot.domain.models import ActionProposal


class SwVideoRecoveryError(RuntimeError):
    """SW 恢复动作未能得到可确认的成功结果。"""


class SwVideoRecoveryAuthError(SwVideoRecoveryError):
    """DG 缺少服务身份，或 SW 拒绝该身份。"""


class SwVideoRecoveryNotFoundError(SwVideoRecoveryError):
    """SW 恢复资源或私有路由不存在。"""


class SwVideoRecoveryRejectedError(SwVideoRecoveryError):
    """SW 原子前置条件不再成立，恢复动作没有产生副作用。"""


class SwVideoRecoveryUpstreamError(SwVideoRecoveryError):
    """SW 明确返回了不可接受的应用级失败。"""


class SwVideoRecoveryReceiptMissingError(SwVideoRecoveryError):
    """对账 GET 返回 404；调用方可以使用同一 key 安全重发 POST。"""


def _positive_int(params: dict[str, Any], key: str) -> int:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ParamValidationError(f"{SW_VIDEO_RECOVERY_ACTION}.{key} 必须为正整数")
    return value


class SwVideoRecoveryActionRunner:
    """将单一白名单动作映射到 SW 的租约过期恢复接口。"""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        service_name: str = "flowpilot",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url.strip():
            raise SwVideoRecoveryError("缺少 SW_VIDEO_BASE_URL，不能调用 SW 恢复接口")
        if not service_token.strip():
            raise SwVideoRecoveryAuthError("缺少 SW_VIDEO_SERVICE_TOKEN，拒绝无身份 SW 写调用")
        if not service_name.strip():
            raise SwVideoRecoveryAuthError("SW_VIDEO_SERVICE_NAME 不能为空")
        self._base_url = base_url.strip().rstrip("/")
        self._service_token = service_token.strip()
        self._service_name = service_name.strip()
        # 写操作必须与只读调查使用同一条显式服务间直连边界，避免继承
        # HTTP_PROXY 后错误地经由代理发送私有恢复请求。
        self._client = client or httpx.AsyncClient(timeout=5.0, trust_env=False)
        self._owns_client = client is None

    @classmethod
    def from_env(cls) -> SwVideoRecoveryActionRunner:
        return cls(
            base_url=os.environ.get("SW_VIDEO_BASE_URL", ""),
            service_token=os.environ.get("SW_VIDEO_SERVICE_TOKEN", ""),
            service_name=os.environ.get("SW_VIDEO_SERVICE_NAME", "flowpilot"),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self, *, trace_id: str, idempotency_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._service_token}",
            "X-FlowPilot-Service": self._service_name,
            "X-Trace-Id": trace_id,
            "Idempotency-Key": idempotency_key,
        }

    @staticmethod
    def _parse_receipt(payload: Any, *, expected_video_id: int, idempotency_key: str) -> dict[str, Any]:
        """校验 SW 回执最小合同，只保留可审计的安全字段。"""
        if not isinstance(payload, dict) or payload.get("code") != 1:
            message = payload.get("msg") if isinstance(payload, dict) else None
            detail = str(message)[:256] if message else "未知应用级失败"
            raise SwVideoRecoveryRejectedError(f"SW 恢复接口 Result 失败: {detail}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ActionOutcomeUnknownError("SW 返回成功但回执无法解析")
        status = data.get("status")
        if status not in {"ACCEPTED", "REJECTED"}:
            raise ActionOutcomeUnknownError("SW 返回成功但回执状态未知")
        if data.get("videoId") != expected_video_id or data.get("idempotencyKey") != idempotency_key:
            raise SwVideoRecoveryRejectedError("SW 回执的 videoId 或幂等键与本次提案不一致")
        recovery_id = data.get("recoveryId")
        if not isinstance(recovery_id, (str, int)) or not str(recovery_id):
            raise ActionOutcomeUnknownError("SW 返回成功但缺少 recoveryId")
        if status == "ACCEPTED" and data.get("outboxId") is None:
            raise ActionOutcomeUnknownError("SW 返回 ACCEPTED 但缺少 outboxId")
        return {
            "recovery_id": str(recovery_id),
            "video_id": expected_video_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "reason": data.get("reason"),
            "outbox_id": str(data["outboxId"]) if data.get("outboxId") is not None else None,
            "trace_id": data.get("traceId"),
            "requested_by": data.get("requestedBy"),
            "replayed": bool(data.get("replayed", False)),
            "created_at": data.get("createdAt"),
        }

    async def _request_receipt(
        self, method: str, *, video_id: int, trace_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        path = (
            f"/video/api/private/processing/{video_id}/{'recover-expired' if method == 'POST' else 'recovery-status'}"
        )
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(trace_id=trace_id, idempotency_key=idempotency_key),
            )
        except httpx.TimeoutException as exc:
            raise ActionOutcomeUnknownError(f"SW 恢复请求超时: {path}") from exc
        except httpx.HTTPError as exc:
            raise ActionOutcomeUnknownError(f"SW 恢复请求失败: {path}") from exc

        if response.status_code in (401, 403):
            raise SwVideoRecoveryAuthError(f"SW 拒绝恢复服务身份（status={response.status_code}）")
        if response.status_code == 404 and method == "GET":
            raise SwVideoRecoveryReceiptMissingError(f"SW 未找到恢复回执: {path}")
        if response.status_code == 404:
            raise SwVideoRecoveryNotFoundError(f"SW 恢复资源不存在或不可访问: {path}")
        if response.status_code == 409:
            raise SwVideoRecoveryRejectedError("SW 拒绝幂等键与视频或服务身份不一致的请求")
        if response.status_code >= 500:
            raise ActionOutcomeUnknownError(f"SW 恢复接口暂不可用（HTTP {response.status_code}）")
        if response.is_error:
            raise SwVideoRecoveryUpstreamError(f"SW 恢复接口返回 HTTP {response.status_code}: {path}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ActionOutcomeUnknownError("SW 恢复接口返回非 JSON 响应") from exc
        return self._parse_receipt(payload, expected_video_id=video_id, idempotency_key=idempotency_key)

    def _validated_target(self, proposal: ActionProposal) -> tuple[str, int, int, str]:
        if proposal.action != SW_VIDEO_RECOVERY_ACTION:
            raise UnsupportedBusinessActionError(f"SW 视频恢复适配器不支持动作 {proposal.action!r}")
        validate_params(proposal.action, proposal.params)

        ticket_id = proposal.params["ticket_id"]
        if not isinstance(ticket_id, str) or ticket_id != proposal.ticket_id:
            raise ParamValidationError("恢复动作 params.ticket_id 必须与提案 ticket_id 一致")
        creator_id = _positive_int(proposal.params, "creator_id")
        video_id = _positive_int(proposal.params, "video_id")
        trace_id = proposal.params["trace_id"]
        if not isinstance(trace_id, str) or not trace_id.strip() or len(trace_id) > 128:
            raise ParamValidationError("恢复动作 trace_id 必须为 1-128 字符的非空字符串")

        return ticket_id, creator_id, video_id, trace_id

    @staticmethod
    def _result(
        proposal: ActionProposal, *, ticket_id: str, creator_id: int, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": "sw-video-recovery",
            "action": proposal.action,
            "business_result": {
                "ticket_id": ticket_id,
                "creator_id": creator_id,
                **receipt,
            },
        }

    async def run(self, proposal: ActionProposal, *, idempotency_key: str) -> dict[str, Any]:
        ticket_id, creator_id, video_id, trace_id = self._validated_target(proposal)
        receipt = await self._request_receipt(
            "POST", video_id=video_id, trace_id=trace_id, idempotency_key=idempotency_key
        )
        if receipt["status"] == "REJECTED":
            raise SwVideoRecoveryRejectedError(f"SW 原子校验未通过: {receipt['reason'] or 'PRECONDITION_NOT_MET'}")
        return self._result(proposal, ticket_id=ticket_id, creator_id=creator_id, receipt=receipt)

    async def reconcile(self, proposal: ActionProposal, *, idempotency_key: str) -> ReconciliationOutcome:
        ticket_id, creator_id, video_id, trace_id = self._validated_target(proposal)
        try:
            receipt = await self._request_receipt(
                "GET", video_id=video_id, trace_id=trace_id, idempotency_key=idempotency_key
            )
        except SwVideoRecoveryReceiptMissingError:
            receipt = await self._request_receipt(
                "POST", video_id=video_id, trace_id=trace_id, idempotency_key=idempotency_key
            )
        except ActionOutcomeUnknownError as exc:
            return ReconciliationOutcome(
                status="unknown",
                result={"ok": False, "adapter": "sw-video-recovery", "detail": str(exc)},
            )

        if receipt["status"] == "REJECTED":
            return ReconciliationOutcome(
                status="failed",
                result={
                    "ok": False,
                    "adapter": "sw-video-recovery",
                    "action": proposal.action,
                    "business_result": receipt,
                },
            )
        return ReconciliationOutcome(
            status="succeeded",
            result=self._result(proposal, ticket_id=ticket_id, creator_id=creator_id, receipt=receipt),
        )
