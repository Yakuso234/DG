"""FlowPilot 的结构化模型端口与无密钥 Fake Model。

模型只给出分诊和处置建议；领域代码仍是动作、参数、风险与审批的唯一权威。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class ModelOutputValidationError(ValueError):
    """模型返回值不满足当前工单场景的受控合同。"""


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


def structured_model_from_env() -> StructuredFlowPilotModel | None:
    """选择模型建议层；默认 deterministic，避免隐式网络/密钥依赖。"""
    provider = os.environ.get("FLOWPILOT_STRUCTURED_MODEL", "deterministic").strip().lower()
    if provider == "deterministic":
        return None
    if provider == "fake":
        return FakeStructuredFlowPilotModel()
    raise ValueError(f"FLOWPILOT_STRUCTURED_MODEL 只能是 deterministic 或 fake，实际为 {provider!r}")
