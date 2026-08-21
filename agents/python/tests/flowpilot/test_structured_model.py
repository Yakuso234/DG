from __future__ import annotations

import pytest

from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION
from flowpilot.structured_model import (
    FakeStructuredFlowPilotModel,
    ModelOutputValidationError,
    ResolutionModelOutput,
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
    with pytest.raises(ValueError, match="deterministic 或 fake"):
        structured_model_from_env()
