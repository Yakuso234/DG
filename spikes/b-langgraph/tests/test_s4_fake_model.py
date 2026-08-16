"""S4 Fake Model 全链路：无网络、无真实 Key 下跑通 S1-S3 核心链路。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from b_langgraph.fake_model import FakeModel, TICKET_ID, TOOL_NAME, ToolCall
from b_langgraph.graph import build_graph, initial_state
from shared.domain import ActionProposal, Ticket, TicketStatus

FAKE_MODEL_SRC = Path(__file__).resolve().parents[1] / "src" / "b_langgraph" / "fake_model.py"


@pytest.mark.scenario("S4")
def test_s4_fake_model_deterministic_contract() -> None:
    model = FakeModel()
    round1 = model.next()
    assert isinstance(round1, ToolCall)
    assert round1.name == TOOL_NAME
    assert round1.arguments == {"ticket_id": TICKET_ID}

    round2 = model.next()
    assert isinstance(round2, ActionProposal)
    assert round2.action == "restart_pipeline"
    assert round2.risk == "high"
    assert round2.evidence_tools == (TOOL_NAME,)

    assert model.next() is None  # 停止


@pytest.mark.scenario("S4")
def test_s4_fake_model_has_no_network_imports() -> None:
    src = FAKE_MODEL_SRC.read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "import httpx",
        "import requests",
        "import urllib",
        "import aiohttp",
        "from httpx",
        "from requests",
        "from urllib",
        "from aiohttp",
    ):
        assert forbidden not in src, f"FakeModel 不得含网络导入: {forbidden}"


@pytest.mark.scenario("S4")
def test_s4_fake_model_full_chain_no_network() -> None:
    # 网络守卫：阻断 DNS 解析与真实 TCP 建连（这是"网络调用"的入口）。
    # 注意：不 patch socket.socket.connect —— Windows 上 asyncio 事件循环用
    # socketpair 自建回环自管道，会调用 connect()，属于事件循环内部行为，非网络。
    def _forbid(*args, **kwargs):
        raise AssertionError("network/socket access forbidden under Fake Model")

    ticket = Ticket(id=TICKET_ID, title="pipeline stalled", status=TicketStatus.TRIAGED)
    config = {"configurable": {"thread_id": TICKET_ID}}

    with mock.patch("socket.getaddrinfo", side_effect=_forbid), mock.patch(
        "socket.create_connection", side_effect=_forbid
    ):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        saver = SqliteSaver(conn)
        graph = build_graph(checkpointer=saver)

        graph.invoke(initial_state(ticket), config)
        snap = graph.get_state(config)
        assert snap.values["ticket"]["status"] == TicketStatus.WAITING_APPROVAL.value
        assert len(snap.values["ticket"]["evidence"]) == 1

        graph.invoke(Command(resume="approved"), config)
        final = graph.get_state(config)
        ticket_final = Ticket.from_dict(final.values["ticket"])
        assert ticket_final.status == TicketStatus.RESOLVED
        assert ticket_final.executed == ["restart_pipeline"]
        conn.close()
