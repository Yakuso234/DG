"""S3 持久化 HITL：SqliteSaver 跨进程恢复 + 审批 + 不重复执行。"""
from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from b_langgraph.graph import build_graph, initial_state
from shared.domain import ApprovalRequiredError, Ticket, TicketStatus, execute_proposal

TICKET_ID = "T-1001"
CONFIG = {"configurable": {"thread_id": TICKET_ID}}
# 沙箱下：系统临时目录不可写；tempfile.mkdtemp 用 0o700 建目录，Windows 沙箱会把
# 该权限映射成 sqlite 无法写入的 ACL。改用 os.makedirs（默认 0o777）+ 工作区目录。
PROJECT_DIR = Path(__file__).resolve().parents[1]


def _initial_ticket() -> Ticket:
    return Ticket(id=TICKET_ID, title="pipeline stalled", status=TicketStatus.TRIAGED)


@pytest.mark.scenario("S3")
def test_s3_persistent_hitl_recovery() -> None:
    tmp_dir = PROJECT_DIR / ("b-langgraph-hilt-" + uuid.uuid4().hex[:12])
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        db = tmp_dir / "checkpoints.sqlite"
        _run_s3(db)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_s3(db: Path) -> None:
    # ---- 进程 1：运行到 WAITING_APPROVAL 挂起点，持久化后彻底销毁运行时 ----
    conn1 = sqlite3.connect(db, check_same_thread=False)
    saver1 = SqliteSaver(conn1)
    graph1 = build_graph(checkpointer=saver1)
    graph1.invoke(initial_state(_initial_ticket()), CONFIG)

    snap1 = graph1.get_state(CONFIG)
    assert snap1.values["ticket"]["status"] == TicketStatus.WAITING_APPROVAL.value
    assert len(snap1.values["ticket"]["evidence"]) == 1
    # 断言挂起点确在 await_approval（interrupt 恢复点正确）。
    assert "await_approval" in snap1.next

    conn1.close()
    del graph1, saver1, conn1  # 模拟进程被杀

    # ---- 进程 2：新 SqliteSaver 连同一文件恢复线程 ----
    conn2 = sqlite3.connect(db, check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    graph2 = build_graph(checkpointer=saver2)

    snap2 = graph2.get_state(CONFIG)
    assert snap2.values["ticket"]["status"] == TicketStatus.WAITING_APPROVAL.value
    assert len(snap2.values["ticket"]["evidence"]) == 1

    # ---- 未审批先行：approval 为空时执行器抛 ApprovalRequiredError ----
    ticket2 = Ticket.from_dict(snap2.values["ticket"])
    assert ticket2.approval is None
    with pytest.raises(ApprovalRequiredError):
        execute_proposal(ticket2)

    # ---- 审批后继续：resume with Command 执行到 RESOLVED ----
    graph2.invoke(Command(resume="approved"), CONFIG)
    final = graph2.get_state(CONFIG)
    ticket_final = Ticket.from_dict(final.values["ticket"])
    assert ticket_final.status == TicketStatus.RESOLVED
    assert ticket_final.executed == ["restart_pipeline"]

    # ---- 不重复执行：共享执行器幂等（相同逻辑步骤不得二次执行）----
    execute_proposal(ticket_final)
    assert ticket_final.executed == ["restart_pipeline"]

    conn2.close()

    # ---- 进程 3：再次从同一文件恢复，executed 仍为 1（恢复/重放不重复）----
    conn3 = sqlite3.connect(db, check_same_thread=False)
    saver3 = SqliteSaver(conn3)
    graph3 = build_graph(checkpointer=saver3)
    snap3 = graph3.get_state(CONFIG)
    ticket3 = Ticket.from_dict(snap3.values["ticket"])
    assert ticket3.status == TicketStatus.RESOLVED
    assert ticket3.executed == ["restart_pipeline"]
    assert len(ticket3.executed) == 1
    conn3.close()
