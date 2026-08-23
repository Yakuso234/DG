from __future__ import annotations

from types import SimpleNamespace

import pytest

from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION
from flowpilot.structured_model import (
    FakeStructuredFlowPilotModel,
    ModelOutputValidationError,
    QwenStructuredFlowPilotModel,
    ResolutionModelInput,
    ResolutionModelOutput,
    StructuredModelProviderError,
    TriageModelInput,
    TriageModelOutput,
    structured_model_from_env,
)
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot


def _gateway() -> MockSwVideoOpsGateway:
    return MockSwVideoOpsGateway(
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


class _FakeCompletions:
    def __init__(self, contents: list[str] | None = None, error: Exception | None = None) -> None:
        self.contents = list(contents or [])
        self.error = error
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.contents.pop(0)))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )


def _qwen_model(completions: _FakeCompletions) -> QwenStructuredFlowPilotModel:
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return QwenStructuredFlowPilotModel(api_key="test-key", client=client)


async def test_fake_structured_model_is_visible_but_cannot_control_proposal_scope_or_risk() -> None:
    model = FakeStructuredFlowPilotModel(
        triage_output=TriageModelOutput("video_processing_stalled", 5, "model suggested high priority"),
        resolution_output=ResolutionModelOutput(SW_VIDEO_RECOVERY_ACTION, "model suggested recovery"),
    )

    state = await build_graph(_gateway(), model=model).ainvoke(
        initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-model")
    )

    assert state["triage"] == {
        "category": "video_processing_stalled",
        "priority": 5,
        "rationale": "model suggested high priority",
        "source": "structured-model",
    }
    assert state["resolution_suggestion"] == {
        "action": SW_VIDEO_RECOVERY_ACTION,
        "rationale": "model suggested recovery",
        "source": "structured-model",
    }
    assert state["proposal"]["params"] == {
        "ticket_id": "ticket-1",
        "creator_id": 7,
        "video_id": 9,
        "trace_id": "trace-model",
    }
    assert state["proposal"]["risk"] == "high"


async def test_model_cannot_suggest_an_out_of_contract_action() -> None:
    model = FakeStructuredFlowPilotModel(resolution_output=ResolutionModelOutput("delete_video", "unsafe"))

    with pytest.raises(ModelOutputValidationError, match="白名单"):
        await build_graph(_gateway(), model=model).ainvoke(
            initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-model-action")
        )


async def test_model_cannot_return_invalid_triage_contract() -> None:
    model = FakeStructuredFlowPilotModel(triage_output=TriageModelOutput("billing", 6, "wrong domain"))

    with pytest.raises(ModelOutputValidationError, match="分诊模型"):
        await build_graph(_gateway(), model=model).ainvoke(
            initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-model-triage")
        )


def test_model_factory_is_explicit_and_defaults_to_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLOWPILOT_STRUCTURED_MODEL", raising=False)
    assert structured_model_from_env() is None

    monkeypatch.setenv("FLOWPILOT_STRUCTURED_MODEL", "fake")
    assert isinstance(structured_model_from_env(), FakeStructuredFlowPilotModel)

    monkeypatch.setenv("FLOWPILOT_STRUCTURED_MODEL", "openai")
    with pytest.raises(ValueError, match="deterministic、fake 或 qwen"):
        structured_model_from_env()


async def test_qwen_provider_uses_json_mode_and_validates_both_contracts() -> None:
    completions = _FakeCompletions(
        [
            '{"category":"video_processing_stalled","priority":4,"rationale":"lease expired"}',
            '{"action":"recover_expired_video_processing","rationale":"approval required"}',
        ]
    )
    model = _qwen_model(completions)

    triage = await model.triage(TriageModelInput("ticket-1", 7, 9, "trace-1"))
    resolution = await model.resolve(ResolutionModelInput("ticket-1", 7, 9, "trace-1", "PROCESSING", "expired"))

    assert triage.category == "video_processing_stalled"
    assert triage.priority == 4
    assert triage.rationale == "lease expired"
    assert resolution.action == "recover_expired_video_processing"
    assert resolution.rationale == "approval required"
    assert triage.metrics is not None
    assert triage.metrics.input_tokens == 11
    assert triage.metrics.output_tokens == 7
    assert triage.metrics.total_tokens == 18
    assert resolution.metrics is not None
    assert resolution.metrics.task == "resolve"
    assert all(item["response_format"] == {"type": "json_object"} for item in completions.requests)
    assert all(item["temperature"] == 0 for item in completions.requests)


async def test_qwen_provider_rejects_invalid_json_contract() -> None:
    model = _qwen_model(_FakeCompletions(['{"category":"billing","priority":9}']))

    with pytest.raises(ModelOutputValidationError, match="结构化合同"):
        await model.triage(TriageModelInput("ticket-1", 7, 9, "trace-1"))


async def test_qwen_provider_sanitizes_provider_errors() -> None:
    model = _qwen_model(_FakeCompletions(error=RuntimeError("secret provider response")))

    with pytest.raises(StructuredModelProviderError, match="RuntimeError") as captured:
        await model.triage(TriageModelInput("ticket-1", 7, 9, "trace-1"))
    assert "secret provider response" not in str(captured.value)


def test_qwen_factory_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLOWPILOT_STRUCTURED_MODEL", "qwen")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        structured_model_from_env()

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    model = structured_model_from_env()
    assert isinstance(model, QwenStructuredFlowPilotModel)
    assert model.model_name == "qwen-plus"
