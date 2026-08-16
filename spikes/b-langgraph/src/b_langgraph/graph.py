"""LangGraph 1.x 图：调查 -> 审批挂起(HITL) -> 执行。

状态用 dict 承载 Ticket.to_dict()（可被 SqliteSaver 的 JsonPlusSerializer 序列化），
节点内用 shared.domain.Ticket.from_dict 重建领域对象；执行器直接用
shared.execute_proposal（自带高风险审批校验 + executed 幂等）。
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from shared.domain import (
    ActionProposal,
    Evidence,
    Ticket,
    TicketStatus,
    execute_proposal,
    utc_now_iso,
)

from .fake_model import FakeModel, TOOL_NAME
from .mcp_tools import MCP_SERVER_NAME, call_ticket_mcp_tool_sync


class GraphState(TypedDict, total=False):
    ticket: dict[str, Any]
    tool_log: list[str]


def initial_state(ticket: Ticket) -> GraphState:
    """构造图的初始状态。"""
    return {"ticket": ticket.to_dict(), "tool_log": []}


def investigate_node(state: GraphState) -> dict[str, Any]:
    """调查：FakeModel 第 1 轮调 MCP 读工具 -> 归一 Evidence -> 第 2 轮产出 high 提案。"""
    ticket = Ticket.from_dict(state["ticket"])
    ticket.transition(TicketStatus.INVESTIGATING)

    model = FakeModel()
    tool_call = model.next()
    assert tool_call is not None and tool_call.name == TOOL_NAME

    result = call_ticket_mcp_tool_sync(tool_call.name, tool_call.arguments)
    assert result.is_error is False, result.structured_content

    ticket.evidence.append(
        Evidence(
            tool=tool_call.name,
            source=MCP_SERVER_NAME,
            data=result.structured_content,
            collected_at=utc_now_iso(),
        )
    )

    proposal = model.next()
    assert isinstance(proposal, ActionProposal)
    ticket.proposal = proposal.to_dict()
    ticket.transition(TicketStatus.PROPOSED)
    ticket.transition(TicketStatus.WAITING_APPROVAL)

    tool_log = list(state.get("tool_log", [])) + [tool_call.name]
    return {"ticket": ticket.to_dict(), "tool_log": tool_log}


def await_approval_node(state: GraphState) -> dict[str, Any]:
    """人工审批挂起点：interrupt 后暂停，恢复值即审批结论。"""
    approval = interrupt(
        {"ticket_id": state["ticket"]["id"], "question": "approve_high_risk_action"}
    )
    ticket = Ticket.from_dict(state["ticket"])
    ticket.approval = approval
    return {"ticket": ticket.to_dict()}


def execute_node(state: GraphState) -> dict[str, Any]:
    """执行：共享 execute_proposal 强制高风险审批 + 幂等。"""
    ticket = Ticket.from_dict(state["ticket"])
    ticket.transition(TicketStatus.EXECUTING)
    execute_proposal(ticket)
    ticket.transition(TicketStatus.RESOLVED)
    return {"ticket": ticket.to_dict()}


def build_graph(checkpointer: Any = None) -> Any:
    """构建线性图：investigate -> await_approval(interrupt) -> execute -> END。"""
    builder = StateGraph(GraphState)
    builder.add_node("investigate", investigate_node)
    builder.add_node("await_approval", await_approval_node)
    builder.add_node("execute", execute_node)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "await_approval")
    builder.add_edge("await_approval", "execute")
    builder.add_edge("execute", END)
    return builder.compile(checkpointer=checkpointer)
