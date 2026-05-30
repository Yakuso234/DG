"""Unit tests for the pure helpers in shared.usage_db (Track D).

The DB-insert functions need a live pool + schema (covered by integration tests);
these cover the deterministic, no-DB parts: JSON coercion and the timer.
"""

from __future__ import annotations

import json
import time

from shared.usage_db import UsageTimer, _safe_json


def test_safe_json_serializes_dict() -> None:
    assert json.loads(_safe_json({"a": 1, "b": "x"})) == {"a": 1, "b": "x"}


def test_safe_json_none_returns_none() -> None:
    assert _safe_json(None) is None


def test_safe_json_coerces_unknown_objects() -> None:
    class Thing:
        def __str__(self) -> str:
            return "thing-repr"

    # default=str makes arbitrary values serializable rather than raising.
    assert "thing-repr" in _safe_json({"obj": Thing()})


def test_safe_json_unserializable_returns_error_marker() -> None:
    # A non-string dict key cannot be JSON-encoded -> the except branch fires.
    assert json.loads(_safe_json({(1, 2): "tuple-key"})) == {"error": "unserializable"}


def test_usage_timer_measures_nonnegative_duration() -> None:
    with UsageTimer() as timer:
        time.sleep(0.001)
    assert isinstance(timer.duration_ms, int)
    assert timer.duration_ms >= 0


def test_usage_timer_zero_before_exit() -> None:
    timer = UsageTimer()
    assert timer.duration_ms == 0
