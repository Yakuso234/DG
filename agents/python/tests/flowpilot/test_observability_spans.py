from __future__ import annotations

from types import SimpleNamespace

import pytest

import flowpilot.observability as observability
from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.structured_model import QwenStructuredFlowPilotModel, TriageModelInput
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot


class _FakeSpan:
    def __init__(self, name: str, attributes: dict) -> None:
        self.name = name
        self.attributes = dict(attributes)
        self.exceptions: list[Exception] = []
        self.status = None

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: Exception) -> None:
        self.exceptions.append(exc)

    def set_status(self, code, description: str) -> None:
        self.status = (code, description)


class _SpanContext:
    def __init__(self, span: _FakeSpan) -> None:
        self.span = span

    def __enter__(self) -> _FakeSpan:
        return self.span

    def __exit__(self, *_args) -> None:
        return None


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def start_as_current_span(self, name: str, *, attributes: dict) -> _SpanContext:
        span = _FakeSpan(name, attributes)
        self.spans.append(span)
        return _SpanContext(span)


class _FakeCompletions:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"category":"video_processing_stalled","priority":4,"rationale":"evidence only"}'
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
        )


async def test_agent_nodes_emit_low_sensitivity_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _FakeTracer()
    monkeypatch.setattr(observability, "_tracer", lambda: tracer)
    observability.set_trace_id("trace-span-test")
    gateway = MockSwVideoOpsGateway(
        [VideoProcessingSnapshot(7, 9, "PROCESSING", "PROCESSING", 1, "expired", "secret error", "now", "seed")]
    )

    await build_graph(gateway).ainvoke(
        initial_state(ticket_id="ticket-span", creator_id=7, video_id=9, trace_id="trace-span-test")
    )

    assert [span.name for span in tracer.spans] == [
        "flowpilot.agent.triage",
        "flowpilot.agent.investigation",
        "flowpilot.agent.resolution",
        "flowpilot.agent.risk_review",
    ]
    assert all(span.attributes["flowpilot.trace_id"] == "trace-span-test" for span in tracer.spans)
    serialized = str([span.attributes for span in tracer.spans])
    assert "secret error" not in serialized
    assert "evidence" not in serialized.lower()


async def test_qwen_span_records_usage_without_prompt_or_response(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _FakeTracer()
    monkeypatch.setattr(observability, "_tracer", lambda: tracer)
    client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    model = QwenStructuredFlowPilotModel(api_key="test-key", client=client)

    await model.triage(TriageModelInput("ticket-span", 7, 9, "trace-span-test"))

    span = tracer.spans[0]
    assert span.name == "flowpilot.model.call"
    assert span.attributes["gen_ai.usage.input_tokens"] == 20
    assert span.attributes["gen_ai.usage.output_tokens"] == 8
    assert span.attributes["flowpilot.model.total_tokens"] == 28
    serialized = str(span.attributes)
    assert "evidence only" not in serialized
    assert "test-key" not in serialized


def test_span_records_exception_and_marks_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _FakeTracer()
    monkeypatch.setattr(observability, "_tracer", lambda: tracer)

    with pytest.raises(RuntimeError, match="boom"):
        with observability.flowpilot_span("flowpilot.failure"):
            raise RuntimeError("boom")

    assert len(tracer.spans[0].exceptions) == 1
    assert tracer.spans[0].status is not None
