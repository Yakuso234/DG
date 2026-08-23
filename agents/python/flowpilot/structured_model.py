"""FlowPilot 的结构化模型端口、无密钥 Fake Model 与 Qwen Provider。

模型只给出分诊和处置建议；领域代码仍是动作、参数、风险与审批的唯一权威。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from flowpilot.observability import flowpilot_span


class ModelOutputValidationError(ValueError):
    """模型返回值不满足当前工单场景的受控合同。"""


class StructuredModelProviderError(RuntimeError):
    """模型提供商调用失败；异常信息不得包含 API Key 或原始响应。"""


@dataclass(frozen=True)
class ModelCallMetrics:
    """单次模型调用的安全用量摘要，不包含 Prompt、响应正文或供应商密钥。"""

    task: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int

    def to_dict(self) -> dict[str, int | str | None]:
        return asdict(self)


@dataclass(frozen=True)
class TriageModelInput:
    ticket_id: str
    creator_id: int
    video_id: int
    trace_id: str


@dataclass(frozen=True)
class TriageModelOutput:
    category: str
    priority: int
    rationale: str = ""
    metrics: ModelCallMetrics | None = None


@dataclass(frozen=True)
class ResolutionModelInput:
    ticket_id: str
    creator_id: int
    video_id: int
    trace_id: str
    processing_status: str | None
    lease_expire_at: str | None


@dataclass(frozen=True)
class ResolutionModelOutput:
    action: str
    rationale: str = ""
    metrics: ModelCallMetrics | None = None


class StructuredFlowPilotModel(Protocol):
    """未来 OpenAI/Azure 实现需遵守的最小、可离线替换的结构化合同。"""

    async def triage(self, request: TriageModelInput) -> TriageModelOutput: ...

    async def resolve(self, request: ResolutionModelInput) -> ResolutionModelOutput: ...


@dataclass(frozen=True)
class FakeStructuredFlowPilotModel:
    """无网络、无 API Key 的确定性模型替身，供图编排和回归使用。"""

    triage_output: TriageModelOutput = TriageModelOutput(
        category="video_processing_stalled", priority=4, rationale="视频仍在处理中，建议进入受控调查"
    )
    resolution_output: ResolutionModelOutput = ResolutionModelOutput(
        action="recover_expired_video_processing", rationale="已有处理状态与租约证据，建议人工审批后恢复"
    )

    async def triage(self, _request: TriageModelInput) -> TriageModelOutput:
        return self.triage_output

    async def resolve(self, _request: ResolutionModelInput) -> ResolutionModelOutput:
        return self.resolution_output


class _QwenTriageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["video_processing_stalled"]
    priority: int = Field(ge=1, le=5)
    rationale: str = Field(default="", max_length=500)


class _QwenResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["recover_expired_video_processing"]
    rationale: str = Field(default="", max_length=500)


class QwenStructuredFlowPilotModel:
    """通过 DashScope OpenAI 兼容接口获取建议，领域层仍负责最终校验。"""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen-plus",
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("缺少 DASHSCOPE_API_KEY，不能启用 Qwen Provider")
        if not model.strip():
            raise ValueError("FLOWPILOT_QWEN_MODEL 不能为空")
        if not base_url.strip():
            raise ValueError("FLOWPILOT_QWEN_BASE_URL 不能为空")
        if timeout_seconds <= 0:
            raise ValueError("FLOWPILOT_QWEN_TIMEOUT_SECONDS 必须大于 0")
        self.model_name = model.strip()
        self.base_url = base_url.rstrip("/")
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
        )

    async def _json_completion(
        self, *, task: str, payload: dict[str, Any], schema: type[BaseModel]
    ) -> tuple[BaseModel, ModelCallMetrics]:
        system_prompt = (
            "你是 FlowPilot 企业工单系统中的受控建议模型。"
            "你只能依据用户给出的 JSON 生成建议，不能生成执行参数或扩大动作范围。"
            "只返回一个 JSON 对象，不要 Markdown、代码块或额外文本。"
        )
        contracts = {
            "triage": (
                "JSON 字段必须且只能是 category、priority、rationale；category 固定为 "
                '"video_processing_stalled"，priority 是 1 到 5 的整数，rationale 不超过 500 字。'
            ),
            "resolve": (
                "JSON 字段必须且只能是 action、rationale；action 固定为 "
                '"recover_expired_video_processing"，rationale 不超过 500 字。'
            ),
        }
        started_at = time.perf_counter()
        with flowpilot_span(
            "flowpilot.model.call",
            {"gen_ai.operation.name": "chat", "gen_ai.request.model": self.model_name, "flowpilot.model.task": task},
        ) as span:
            try:
                response = await self._client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": f"{system_prompt}{contracts[task]}"},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            except Exception as exc:
                raise StructuredModelProviderError(f"Qwen {task} 调用失败（{type(exc).__name__}）") from exc
            usage = getattr(response, "usage", None)
            input_tokens = self._token_value(usage, "prompt_tokens")
            output_tokens = self._token_value(usage, "completion_tokens")
            total_tokens = self._token_value(usage, "total_tokens")
            metrics = ModelCallMetrics(
                task=task,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )
            for key, value in {
                "gen_ai.usage.input_tokens": input_tokens,
                "gen_ai.usage.output_tokens": output_tokens,
                "flowpilot.model.total_tokens": total_tokens,
                "flowpilot.model.latency_ms": metrics.latency_ms,
            }.items():
                if value is not None:
                    span.set_attribute(key, value)

            try:
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty content")
                return schema.model_validate_json(content), metrics
            except (AttributeError, IndexError, TypeError, ValueError) as exc:
                raise ModelOutputValidationError(f"Qwen {task} 返回值不满足结构化合同") from exc

    @staticmethod
    def _token_value(usage: Any, name: str) -> int | None:
        value = getattr(usage, name, None)
        return value if isinstance(value, int) and value >= 0 else None

    async def triage(self, request: TriageModelInput) -> TriageModelOutput:
        result, metrics = await self._json_completion(
            task="triage", payload=asdict(request), schema=_QwenTriageResponse
        )
        assert isinstance(result, _QwenTriageResponse)
        return TriageModelOutput(**result.model_dump(), metrics=metrics)

    async def resolve(self, request: ResolutionModelInput) -> ResolutionModelOutput:
        result, metrics = await self._json_completion(
            task="resolve", payload=asdict(request), schema=_QwenResolutionResponse
        )
        assert isinstance(result, _QwenResolutionResponse)
        return ResolutionModelOutput(**result.model_dump(), metrics=metrics)


def structured_model_from_env() -> StructuredFlowPilotModel | None:
    """选择模型建议层；默认 deterministic，避免隐式网络/密钥依赖。"""
    provider = os.environ.get("FLOWPILOT_STRUCTURED_MODEL", "deterministic").strip().lower()
    if provider == "deterministic":
        return None
    if provider == "fake":
        return FakeStructuredFlowPilotModel()
    if provider == "qwen":
        try:
            timeout_seconds = float(os.environ.get("FLOWPILOT_QWEN_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise ValueError("FLOWPILOT_QWEN_TIMEOUT_SECONDS 必须是数字") from exc
        return QwenStructuredFlowPilotModel(
            api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            model=os.environ.get("FLOWPILOT_QWEN_MODEL", "qwen-plus"),
            base_url=os.environ.get("FLOWPILOT_QWEN_BASE_URL", QwenStructuredFlowPilotModel.DEFAULT_BASE_URL),
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"FLOWPILOT_STRUCTURED_MODEL 只能是 deterministic、fake 或 qwen，实际为 {provider!r}")
