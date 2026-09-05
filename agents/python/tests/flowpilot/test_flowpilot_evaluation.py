import json
from pathlib import Path

from flowpilot.evaluation import FlowPilotDeterministicEvaluator, _run, load_flowpilot_eval_cases
from flowpilot.structured_model import (
    FakeStructuredFlowPilotModel,
    ModelCallMetrics,
    ResolutionModelOutput,
    TriageModelOutput,
)

DATASET = Path(__file__).parents[2] / "evals" / "datasets" / "flowpilot_video_ops.json"
HOLDOUT = Path(__file__).parents[2] / "evals" / "datasets" / "flowpilot_diagnosis_holdout.json"


async def test_flowpilot_video_ops_dataset_passes_deterministic_baseline() -> None:
    cases = load_flowpilot_eval_cases(DATASET)
    summary = await FlowPilotDeterministicEvaluator().evaluate(cases)

    assert summary.total == 30
    assert summary.passed == summary.total
    assert summary.pass_rate == 1.0
    assert summary.p50_latency_ms >= 0
    assert summary.p95_latency_ms >= summary.p50_latency_ms


async def test_injected_error_text_cannot_change_action_or_params() -> None:
    cases = load_flowpilot_eval_cases(DATASET)
    injected = [case for case in cases if "injection" in case.id]
    results = [await FlowPilotDeterministicEvaluator().evaluate_case(case) for case in injected]

    proposal_results = [item for item in results if item.outcome == "proposal"]
    rejection_results = [item for item in results if item.outcome == "reject"]

    assert len(results) == 8
    assert proposal_results and rejection_results and all(item.passed for item in results)
    assert all(item.checks["action_correct"] and item.checks["params_scoped"] for item in proposal_results)
    assert all(item.checks["rejection_reason_correct"] for item in rejection_results)


async def test_missing_lease_has_distinct_rejection_reason() -> None:
    case = next(case for case in load_flowpilot_eval_cases(DATASET) if case.id == "processing-without-lease")

    result = await FlowPilotDeterministicEvaluator().evaluate_case(case)

    assert result.passed is True
    assert result.detail == "missing_lease_evidence"


async def test_diagnosis_holdout_covers_wait_escalate_and_untrusted_error_text() -> None:
    cases = load_flowpilot_eval_cases(HOLDOUT)
    summary = await FlowPilotDeterministicEvaluator().evaluate(cases)

    assert summary.total == 4
    assert summary.passed == 4
    by_case = {result.case_id: result for result in summary.results}
    assert by_case["future-lease-wait"].outcome == "defer"
    assert by_case["future-lease-wait"].detail == "lease_not_expired"
    assert by_case["expired-injection-recover"].outcome == "proposal"
    assert by_case["expired-injection-recover"].checks["params_scoped"] is True


async def test_structured_model_evaluation_reports_tokens_and_model_latency() -> None:
    model = FakeStructuredFlowPilotModel(
        triage_output=TriageModelOutput(
            "video_processing_stalled", 4, "triage", ModelCallMetrics("triage", 10, 4, 14, 100)
        ),
        resolution_output=ResolutionModelOutput("recover", "resolve", ModelCallMetrics("resolve", 12, 5, 17, 200)),
    )
    cases = load_flowpilot_eval_cases(DATASET)

    summary = await FlowPilotDeterministicEvaluator(model).evaluate(cases)

    assert summary.passed == 30
    assert summary.model == "FakeStructuredFlowPilotModel"
    assert summary.model_calls == 42
    assert summary.input_tokens == 444
    assert summary.output_tokens == 180
    assert summary.total_tokens == 624
    assert summary.p50_model_latency_ms == 100
    assert summary.p95_model_latency_ms == 300


async def test_repeat_aggregates_all_samples(capsys) -> None:
    result = await _run(str(DATASET), repeat=2, summary_only=True)
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["dataset_cases"] == 30
    assert payload["runs"] == 2
    assert payload["aggregate"]["total"] == 60
    assert payload["aggregate"]["passed"] == 60
    assert "results" not in payload["aggregate"]
