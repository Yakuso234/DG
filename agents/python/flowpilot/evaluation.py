"""FlowPilot 评测：默认确定性，也可显式使用真实结构化模型。"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.structured_model import (
    ResolutionModelInput,
    ResolutionModelOutput,
    StructuredFlowPilotModel,
    TriageModelInput,
    TriageModelOutput,
    structured_model_from_env,
)
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
    expected_rejection_reason: str | None = None
    expected_diagnosis_decision: str | None = None
    ticket_title: str = ""
    ticket_description: str = ""


@dataclass(frozen=True)
class FlowPilotEvalResult:
    case_id: str
    passed: bool
    latency_ms: float
    outcome: str
    checks: dict[str, bool]
    model_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    model_latency_ms: int = 0
    detail: str = ""


@dataclass(frozen=True)
class FlowPilotEvalSummary:
    total: int
    passed: int
    pass_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    model: str
    model_calls: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    p50_model_latency_ms: float
    p95_model_latency_ms: float
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
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("FlowPilot eval dataset 的 case id 必须唯一")
    for case in cases:
        if case.expected_outcome not in {"proposal", "reject", "defer"}:
            raise ValueError(f"case {case.id} 的 expected_outcome 非法")
        if case.expected_outcome == "proposal" and not case.expected_action:
            raise ValueError(f"case {case.id} 缺少 expected_action")
        if case.expected_outcome == "proposal" and (
            case.expected_rejection_reason is not None or case.expected_diagnosis_decision not in {None, "recover"}
        ):
            raise ValueError(f"case {case.id} 为 proposal 时不能声明非 recover 诊断")
        if case.expected_outcome == "defer" and case.expected_diagnosis_decision not in {"wait", "escalate"}:
            raise ValueError(f"case {case.id} 的 defer 用例必须声明 wait 或 escalate")
    return cases


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


class _RecordingModel:
    def __init__(self, delegate: StructuredFlowPilotModel) -> None:
        self._delegate = delegate
        self.calls: list[dict[str, Any]] = []

    async def triage(self, request: TriageModelInput) -> TriageModelOutput:
        output = await self._delegate.triage(request)
        self.calls.append(
            output.metrics.to_dict()
            if output.metrics is not None
            else {
                "task": "triage",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "latency_ms": 0,
            }
        )
        return output

    async def resolve(self, request: ResolutionModelInput) -> ResolutionModelOutput:
        output = await self._delegate.resolve(request)
        self.calls.append(
            output.metrics.to_dict()
            if output.metrics is not None
            else {
                "task": "resolve",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "latency_ms": 0,
            }
        )
        return output


def _model_measurements(calls: list[dict[str, Any]]) -> dict[str, Any]:
    def total(field: str) -> int | None:
        values = [item.get(field) for item in calls]
        return sum(values) if values and all(isinstance(value, int) for value in values) else None

    return {
        "model_calls": len(calls),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "total_tokens": total("total_tokens"),
        "model_latency_ms": sum(item.get("latency_ms", 0) for item in calls),
    }


def _summarize_results(
    results: list[FlowPilotEvalResult], model: StructuredFlowPilotModel | None
) -> FlowPilotEvalSummary:
    latencies = [item.latency_ms for item in results]
    model_latencies = [item.model_latency_ms for item in results if item.model_calls]
    passed = sum(item.passed for item in results)

    def token_total(field: str) -> int | None:
        values = [getattr(item, field) for item in results]
        return sum(values) if values and all(isinstance(value, int) for value in values) else None

    return FlowPilotEvalSummary(
        total=len(results),
        passed=passed,
        pass_rate=round(passed / len(results), 4) if results else 0.0,
        p50_latency_ms=_percentile(latencies, 0.5),
        p95_latency_ms=_percentile(latencies, 0.95),
        model="deterministic" if model is None else type(model).__name__,
        model_calls=sum(item.model_calls for item in results),
        input_tokens=token_total("input_tokens"),
        output_tokens=token_total("output_tokens"),
        total_tokens=token_total("total_tokens"),
        p50_model_latency_ms=_percentile(model_latencies, 0.5),
        p95_model_latency_ms=_percentile(model_latencies, 0.95),
        results=tuple(results),
    )


class FlowPilotDeterministicEvaluator:
    def __init__(self, model: StructuredFlowPilotModel | None = None) -> None:
        self._model = model

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
        recorder = _RecordingModel(self._model) if self._model is not None else None
        started = time.perf_counter()
        state = await build_graph(gateway, model=recorder).ainvoke(
            initial_state(
                ticket_id=ticket_id,
                creator_id=case.creator_id,
                video_id=case.video_id,
                trace_id=trace_id,
                ticket_title=case.ticket_title,
                ticket_description=case.ticket_description,
            )
        )

        latency = (time.perf_counter() - started) * 1000
        evidence = state["evidence"][0]
        diagnosis = state["diagnosis"]
        proposal = state.get("proposal")
        if not isinstance(proposal, dict):
            checks = {
                "expected_defer": case.expected_outcome in {"reject", "defer"},
                "diagnosis_decision_correct": (
                    diagnosis.get("decision") == case.expected_diagnosis_decision
                    if case.expected_diagnosis_decision is not None
                    else diagnosis.get("decision") in {"wait", "escalate"}
                ),
                "evidence_source": evidence["source"] == "sw-video-ops-mcp",
                "evidence_referenced": diagnosis.get("evidence_ids") == [evidence["id"]],
                "trace_preserved": evidence["data"]["trace_id"] == trace_id,
            }
            if case.expected_rejection_reason is not None:
                checks["rejection_reason_correct"] = diagnosis.get("reason") == case.expected_rejection_reason
            return FlowPilotEvalResult(
                case_id=case.id,
                passed=all(checks.values()),
                latency_ms=latency,
                outcome="reject" if case.expected_outcome == "reject" else "defer",
                checks=checks,
                detail=str(diagnosis.get("reason", "")),
                **_model_measurements(recorder.calls if recorder is not None else []),
            )
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
            "diagnosis_decision_correct": diagnosis.get("decision") == "recover",
        }
        return FlowPilotEvalResult(
            case_id=case.id,
            passed=all(checks.values()),
            latency_ms=latency,
            outcome="proposal",
            checks=checks,
            **_model_measurements(recorder.calls if recorder is not None else []),
        )

    async def evaluate(self, cases: list[FlowPilotEvalCase]) -> FlowPilotEvalSummary:
        results = [await self.evaluate_case(case) for case in cases]
        return _summarize_results(results, self._model)


def _summary_metrics(summary: FlowPilotEvalSummary) -> dict[str, Any]:
    data = summary.to_dict()
    data.pop("results")
    return data


async def _run(
    dataset: str,
    use_structured_model: bool = False,
    repeat: int = 1,
    summary_only: bool = False,
) -> int:
    if repeat < 1:
        raise ValueError("--repeat 必须至少为 1")
    model = structured_model_from_env() if use_structured_model else None
    if use_structured_model and model is None:
        raise ValueError("真实模型评测需要 FLOWPILOT_STRUCTURED_MODEL=qwen 或 fake")
    cases = load_flowpilot_eval_cases(dataset)
    summaries = [await FlowPilotDeterministicEvaluator(model).evaluate(cases) for _ in range(repeat)]
    aggregate = _summarize_results([result for summary in summaries for result in summary.results], model)
    output: dict[str, Any] = aggregate.to_dict()
    if repeat > 1:
        output = {
            "dataset_cases": len(cases),
            "runs": repeat,
            "aggregate": aggregate.to_dict(),
            "per_run": [summary.to_dict() for summary in summaries],
        }
    if summary_only:
        output = _summary_metrics(aggregate)
        if repeat > 1:
            output = {
                "dataset_cases": len(cases),
                "runs": repeat,
                "aggregate": _summary_metrics(aggregate),
                "per_run": [_summary_metrics(summary) for summary in summaries],
            }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if aggregate.passed == aggregate.total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic or structured-model FlowPilot evaluations")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--structured-model-from-env", action="store_true")
    parser.add_argument("--repeat", type=int, default=1, help="同一数据集顺序运行次数，默认 1")
    parser.add_argument("--summary-only", action="store_true", help="仅输出聚合指标，不输出逐条结果")
    args = parser.parse_args()
    return asyncio.run(_run(args.dataset, args.structured_model_from_env, args.repeat, args.summary_only))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
