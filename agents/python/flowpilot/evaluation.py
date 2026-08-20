"""FlowPilot 确定性评测：不依赖 LLM、网络或 PostgreSQL。"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flowpilot.agent_graph import ResolutionNotApplicableError, build_graph, initial_state
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot


@dataclass(frozen=True)
class FlowPilotEvalCase:
    id: str
    creator_id: int
    video_id: int
    video_status: str
    processing_status: str | None
    retry_count: int | None
    lease_expire_at: str | None
    error_summary: str | None
    expected_outcome: str
    expected_action: str | None = None


@dataclass(frozen=True)
class FlowPilotEvalResult:
    case_id: str
    passed: bool
    latency_ms: float
    outcome: str
    checks: dict[str, bool]
    detail: str = ""


@dataclass(frozen=True)
class FlowPilotEvalSummary:
    total: int
    passed: int
    pass_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    results: tuple[FlowPilotEvalResult, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [asdict(item) for item in self.results]
        return data


def load_flowpilot_eval_cases(path: str | Path) -> list[FlowPilotEvalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("FlowPilot eval dataset 必须是非空 JSON 数组")
    cases = [FlowPilotEvalCase(**item) for item in payload]
    for case in cases:
        if case.expected_outcome not in {"proposal", "reject"}:
            raise ValueError(f"case {case.id} 的 expected_outcome 非法")
        if case.expected_outcome == "proposal" and not case.expected_action:
            raise ValueError(f"case {case.id} 缺少 expected_action")
    return cases


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


class FlowPilotDeterministicEvaluator:
    async def evaluate_case(self, case: FlowPilotEvalCase) -> FlowPilotEvalResult:
        trace_id = f"eval-{case.id}"
        ticket_id = f"ticket-{case.id}"
        gateway = MockSwVideoOpsGateway(
            [
                VideoProcessingSnapshot(
                    case.creator_id,
                    case.video_id,
                    case.video_status,
                    case.processing_status,
                    case.retry_count,
                    case.lease_expire_at,
                    case.error_summary,
                    "2026-08-19T00:00:00Z",
                    trace_id,
                )
            ]
        )
        started = time.perf_counter()
        try:
            state = await build_graph(gateway).ainvoke(
                initial_state(
                    ticket_id=ticket_id,
                    creator_id=case.creator_id,
                    video_id=case.video_id,
                    trace_id=trace_id,
                )
            )
        except ResolutionNotApplicableError as exc:
            latency = (time.perf_counter() - started) * 1000
            passed = case.expected_outcome == "reject"
            return FlowPilotEvalResult(
                case.id,
                passed,
                latency,
                "reject",
                {"expected_rejection": passed},
                exc.reason,
            )

        latency = (time.perf_counter() - started) * 1000
        evidence = state["evidence"][0]
        proposal = state["proposal"]
        checks = {
            "expected_proposal": case.expected_outcome == "proposal",
            "action_correct": proposal["action"] == case.expected_action,
            "params_scoped": proposal["params"]
            == {
                "ticket_id": ticket_id,
                "creator_id": case.creator_id,
                "video_id": case.video_id,
                "trace_id": trace_id,
            },
            "evidence_source": evidence["source"] == "sw-video-ops-mcp",
            "evidence_referenced": proposal["evidence_ids"] == [evidence["id"]],
            "risk_authoritative": state["risk_review"]["authoritative_risk"] == "high",
            "trace_preserved": evidence["data"]["trace_id"] == trace_id,
        }
        return FlowPilotEvalResult(case.id, all(checks.values()), latency, "proposal", checks)

    async def evaluate(self, cases: list[FlowPilotEvalCase]) -> FlowPilotEvalSummary:
        results = [await self.evaluate_case(case) for case in cases]
        latencies = [item.latency_ms for item in results]
        passed = sum(item.passed for item in results)
        return FlowPilotEvalSummary(
            total=len(results),
            passed=passed,
            pass_rate=round(passed / len(results), 4) if results else 0.0,
            p50_latency_ms=_percentile(latencies, 0.5),
            p95_latency_ms=_percentile(latencies, 0.95),
            results=tuple(results),
        )


async def _run(dataset: str) -> int:
    summary = await FlowPilotDeterministicEvaluator().evaluate(load_flowpilot_eval_cases(dataset))
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0 if summary.passed == summary.total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic FlowPilot evaluations")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.dataset))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
