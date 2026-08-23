from __future__ import annotations

from flowpilot.demo import run_demo


async def test_mock_demo_runs_the_persisted_api_workflow(database_url, clean_db, tmp_path) -> None:
    result = await run_demo(
        database_url=database_url,
        checkpoint_path=str(tmp_path / "demo.sqlite"),
        trace_id="trace-demo-test",
        initialize_schema=False,
    )

    assert result["mode"] == "mock-no-key"
    assert result["ticket"]["status"] == "RESOLVED"
    assert result["proposal"]["action"] == "recover_expired_video_processing"
    assert result["agent_run"]["agent"] == "flowpilot-main-graph"
    assert result["agent_run"]["trace_id"] == "trace-demo-test"
    assert result["execution"]["status"] == "succeeded"
    assert result["graph_steps_before_approval"] == ["triage", "investigation", "resolution", "risk_review"]
    assert result["graph_steps_after_approval"][-1] == "approval"
    assert result["evidence_count"] == 1
    assert result["mock_business_operations"][0]["op"] == "restart_pipeline"

    repeated = await run_demo(
        database_url=database_url,
        checkpoint_path=str(tmp_path / "demo.sqlite"),
        trace_id="trace-demo-test",
        initialize_schema=False,
    )
    assert repeated["ticket"]["id"] != result["ticket"]["id"]
    assert repeated["ticket"]["status"] == "RESOLVED"
