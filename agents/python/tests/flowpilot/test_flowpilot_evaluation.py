from pathlib import Path

from flowpilot.evaluation import FlowPilotDeterministicEvaluator, load_flowpilot_eval_cases

DATASET = Path(__file__).parents[2] / "evals" / "datasets" / "flowpilot_video_ops.json"


async def test_flowpilot_video_ops_dataset_passes_deterministic_baseline() -> None:
    cases = load_flowpilot_eval_cases(DATASET)
    summary = await FlowPilotDeterministicEvaluator().evaluate(cases)

    assert summary.total == 6
    assert summary.passed == summary.total
    assert summary.pass_rate == 1.0
    assert summary.p50_latency_ms >= 0
    assert summary.p95_latency_ms >= summary.p50_latency_ms


async def test_injected_error_text_cannot_change_action_or_params() -> None:
    cases = load_flowpilot_eval_cases(DATASET)
    injected = [case for case in cases if "injection" in case.id]
    results = [await FlowPilotDeterministicEvaluator().evaluate_case(case) for case in injected]

    assert results and all(item.passed for item in results)
    assert all(item.checks["action_correct"] and item.checks["params_scoped"] for item in results)
