"""Pytest bootstrap + report.json generation for SPIKE-001 Spike A.

1. Adds ``spikes/`` to ``sys.path`` so the shared domain core is importable
   as ``shared.domain`` (contract §2).
2. Aggregates per-scenario test outcomes and writes ``report.json`` at the end
   of the run (contract §6).
"""

from __future__ import annotations

import importlib.metadata
import json
import pathlib
import shutil
import sys
import time
import uuid

import pytest

# --- 1. make spikes/shared importable ---------------------------------------
_SPIKES_DIR = pathlib.Path(__file__).resolve().parents[2]  # spikes/
if str(_SPIKES_DIR) not in sys.path:
    sys.path.insert(0, str(_SPIKES_DIR))

# --- 2. report.json machinery -----------------------------------------------
_SESSION_START = time.monotonic()

_SCENARIO_BY_MARKER = {
    "s1": "S1",
    "s2": "S2",
    "s3": "S3",
    "s4": "S4",
    "s5a": "S5a",
    "s5b": "S5b",
}

_TEST_OUTCOMES: dict[str, str] = {}  # nodeid -> "passed"|"failed"|"skipped"
_SKIP_REASONS: dict[str, str] = {}  # nodeid -> reason string

_S5B_DEFAULT_REASON = (
    "cross-process HTTP transport not exercised: S5b is best-effort and was "
    "not attempted in this run"
)


@pytest.fixture
def tmp_path() -> pathlib.Path:
    """Workspace-local temp dir (the sandbox denies pytest's system-temp
    ``tmp_path``, so we provide our own under ``spikes/a-maf/.spike-tmp``)."""
    base = pathlib.Path(__file__).resolve().parents[1] / ".spike-tmp"
    base.mkdir(parents=True, exist_ok=True)
    directory = base / f"test-{uuid.uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    if call.when not in ("setup", "call"):
        return
    if call.excinfo is None:
        outcome = "passed"
    elif call.excinfo.errisinstance(pytest.skip.Exception):
        outcome = "skipped"
        _SKIP_REASONS[item.nodeid] = str(call.excinfo.value)
    else:
        outcome = "failed"
    _TEST_OUTCOMES[item.nodeid] = outcome


def _scenario_of(item: pytest.Item) -> str | None:
    for marker, scenario in _SCENARIO_BY_MARKER.items():
        if item.get_closest_marker(marker) is not None:
            return scenario
    return None


def _count_glue_lines() -> int:
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "a_maf"
    total = 0
    for path in sorted(src.glob("*.py")):
        total += len(path.read_text(encoding="utf-8").splitlines())
    return total


def _dep(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Aggregate outcomes per scenario.
    by_scenario: dict[str, list[str]] = {}
    for item in session.items:
        scenario = _scenario_of(item)
        if scenario is None:
            continue
        outcome = _TEST_OUTCOMES.get(item.nodeid, "failed")
        by_scenario.setdefault(scenario, []).append(outcome)

    scenarios: dict[str, str] = {}
    for scenario in ("S1", "S2", "S3", "S4", "S5a"):
        outcomes = by_scenario.get(scenario, [])
        if not outcomes:
            scenarios[scenario] = "FAIL"
        elif any(o == "failed" for o in outcomes):
            scenarios[scenario] = "FAIL"
        else:
            scenarios[scenario] = "PASS"

    s5b_outcomes = by_scenario.get("S5b", [])
    if any(o == "failed" for o in s5b_outcomes):
        scenarios["S5b"] = "FAIL"
    elif any(o == "passed" for o in s5b_outcomes):
        scenarios["S5b"] = "PASS"
    else:
        # No S5b tests ran, or they were all skipped.
        scenarios["S5b"] = "SKIPPED-WITH-REASON"
        if s5b_outcomes:
            reasons = [
                _SKIP_REASONS.get(item.nodeid, "skipped")
                for item in session.items
                if _scenario_of(item) == "S5b"
            ]
            if reasons:
                scenarios["S5b"] = "SKIPPED-WITH-REASON: " + "; ".join(reasons)
        else:
            scenarios["S5b"] = "SKIPPED-WITH-REASON: " + _S5B_DEFAULT_REASON

    report = {
        "stack": "a-maf",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_full": sys.version.split()[0],
        "scenarios": scenarios,
        "pytest_exit_code": exitstatus,
        "duration_seconds": round(time.monotonic() - _SESSION_START, 2),
        "deps": {
            "agent-framework": _dep("agent-framework"),
            "agent-framework-core": _dep("agent-framework-core"),
            "mcp": _dep("mcp"),
            "a2a-sdk": _dep("a2a-sdk"),
            "langgraph": _dep("langgraph"),
        },
        "glue_lines": _count_glue_lines(),
        "monkeypatches": [],
    }

    out = pathlib.Path(__file__).resolve().parents[1] / "report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
