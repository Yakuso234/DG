from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from flowpilot.agent_graph import build_graph, initial_state
from flowpilot.sw_video_ops import MockSwVideoOpsGateway, VideoProcessingSnapshot


async def test_langgraph_main_flow_generates_evidence_and_high_risk_proposal() -> None:
    gateway = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-19 10:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    state = await build_graph(gateway).ainvoke(
        initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-p3")
    )

    assert state["steps"] == ["triage", "investigation", "resolution", "risk_review"]
    assert state["evidence"][0]["source"] == "sw-video-ops-mcp"
    assert state["proposal"]["action"] == "recover_expired_video_processing"
    assert state["proposal"]["params"] == {
        "ticket_id": "ticket-1",
        "creator_id": 7,
        "video_id": 9,
        "trace_id": "trace-p3",
    }
    assert state["risk_review"] == {"approved_for_human_review": True, "authoritative_risk": "high"}


async def test_langgraph_refuses_non_processing_scenario() -> None:
    gateway = MockSwVideoOpsGateway(
        [VideoProcessingSnapshot(7, 9, "PUBLISHED", "SUCCEEDED", 0, None, None, "2026-08-19 09:00:00", "seed")]
    )
    with pytest.raises(ValueError, match="PROCESSING"):
        await build_graph(gateway).ainvoke(
            initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-p3")
        )


async def test_langgraph_refuses_processing_task_without_lease_evidence() -> None:
    gateway = MockSwVideoOpsGateway(
        [VideoProcessingSnapshot(7, 9, "PROCESSING", "PROCESSING", 1, None, None, "2026-08-19 09:00:00", "seed")]
    )
    with pytest.raises(ValueError, match="租约到期时间"):
        await build_graph(gateway).ainvoke(
            initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-missing-lease")
        )


async def test_langgraph_interrupts_and_resumes_human_approval() -> None:
    gateway = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-18 00:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    graph = build_graph(gateway, checkpointer=MemorySaver(), require_approval=True)
    config = {"configurable": {"thread_id": "approval-thread"}}

    paused = await graph.ainvoke(
        initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-p4"), config
    )
    assert "__interrupt__" in paused
    assert paused["steps"] == ["triage", "investigation", "resolution", "risk_review"]

    resumed = await graph.ainvoke(Command(resume="approved"), config)
    assert resumed["approval"] == {"decision": "approved"}
    assert resumed["steps"][-1] == "approval"


async def test_langgraph_resumes_approval_from_sqlite_checkpoint(tmp_path) -> None:
    database_path = tmp_path / "approval-checkpoints.sqlite"
    gateway = MockSwVideoOpsGateway(
        [
            VideoProcessingSnapshot(
                7, 9, "PROCESSING", "PROCESSING", 1, "2026-08-18 00:00:00", None, "2026-08-19 09:00:00", "seed"
            )
        ]
    )
    config = {"configurable": {"thread_id": "sqlite-approval-thread"}}

    async with AsyncSqliteSaver.from_conn_string(str(database_path)) as checkpointer:
        await checkpointer.setup()
        paused = await build_graph(gateway, checkpointer=checkpointer, require_approval=True).ainvoke(
            initial_state(ticket_id="ticket-1", creator_id=7, video_id=9, trace_id="trace-p4-sqlite"), config
        )

    assert "__interrupt__" in paused

    async with AsyncSqliteSaver.from_conn_string(str(database_path)) as checkpointer:
        await checkpointer.setup()
        resumed = await build_graph(gateway, checkpointer=checkpointer, require_approval=True).ainvoke(
            Command(resume="denied"), config
        )

    assert resumed["approval"] == {"decision": "denied"}
    assert resumed["steps"][-1] == "approval"
