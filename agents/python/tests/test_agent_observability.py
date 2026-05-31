"""Unit tests for the agentic-timeline step recorder middleware."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.agent_observability import StepRecorderMiddleware, get_steps, reset_steps
from shared.context import current_steps


def _ctx(name: str, args: dict, result=None) -> SimpleNamespace:
    return SimpleNamespace(function=SimpleNamespace(name=name), arguments=args, result=result)


async def test_records_a_step_on_success():
    reset_steps()
    mw = StepRecorderMiddleware()

    async def call_next() -> None:
        return None

    await mw.process(_ctx("search_products", {"q": "laptop"}, {"results": [1, 2]}), call_next)

    steps = get_steps()
    assert len(steps) == 1
    assert steps[0]["tool_name"] == "search_products"
    assert steps[0]["status"] == "success"
    assert steps[0]["tool_input"] == {"q": "laptop"}
    assert "duration_ms" in steps[0]


async def test_noop_outside_request_scope():
    current_steps.set(None)  # no active capture
    mw = StepRecorderMiddleware()

    async def call_next() -> None:
        return None

    await mw.process(_ctx("anything", {}), call_next)
    assert get_steps() == []


async def test_records_error_status_and_reraises():
    reset_steps()
    mw = StepRecorderMiddleware()

    async def call_next() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await mw.process(_ctx("boom_tool", {}), call_next)

    steps = get_steps()
    assert steps and steps[0]["status"] == "error"
