"""SPIKE-001 共享领域核心。

纯 Python + 标准库，零框架依赖。两套技术栈（MAF / LangGraph）必须直接
复用本模块，不得各自实现语义不同的状态机/证据/方案模型。

契约详见 docs/spikes/SPIKE-001-agent-runtime-contract.md。
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class TicketStatus(str, enum.Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    PROPOSED = "PROPOSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# 唯一合法转移表：两套实现必须引用它，不允许复制第二份。
LEGAL_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.NEW: frozenset({TicketStatus.TRIAGED}),
    TicketStatus.TRIAGED: frozenset({TicketStatus.INVESTIGATING, TicketStatus.ESCALATED}),
    TicketStatus.INVESTIGATING: frozenset({TicketStatus.PROPOSED, TicketStatus.ESCALATED, TicketStatus.FAILED}),
    TicketStatus.PROPOSED: frozenset({TicketStatus.WAITING_APPROVAL}),
    TicketStatus.WAITING_APPROVAL: frozenset({TicketStatus.EXECUTING, TicketStatus.ESCALATED}),
    TicketStatus.EXECUTING: frozenset({TicketStatus.RESOLVED, TicketStatus.FAILED}),
    TicketStatus.RESOLVED: frozenset(),
    TicketStatus.ESCALATED: frozenset(),
    TicketStatus.FAILED: frozenset(),
}


class IllegalTransitionError(ValueError):
    """非法状态转移。"""


class ApprovalRequiredError(RuntimeError):
    """高风险提案未经批准就执行。"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Evidence:
    """工具产出证据：必须带来源与时间，不允许匿名证据。"""

    tool: str
    source: str  # MCP server 名
    data: dict[str, Any]
    collected_at: str  # ISO 8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionProposal:
    """结构化处置计划：动作、参数、证据引用、风险级别。"""

    action: str
    params: dict[str, Any]
    evidence_tools: tuple[str, ...]
    risk: str  # "low" | "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "params": self.params,
            "evidence_tools": list(self.evidence_tools),
            "risk": self.risk,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionProposal":
        return cls(
            action=d["action"],
            params=d["params"],
            evidence_tools=tuple(d["evidence_tools"]),
            risk=d["risk"],
        )


@dataclass
class Ticket:
    id: str
    title: str
    status: TicketStatus = TicketStatus.NEW
    evidence: list[Evidence] = field(default_factory=list)
    proposal: dict[str, Any] | None = None
    approval: str | None = None  # None | "approved" | "rejected"
    executed: list[str] = field(default_factory=list)

    def transition(self, target: TicketStatus) -> None:
        if target not in LEGAL_TRANSITIONS[self.status]:
            raise IllegalTransitionError(
                f"{self.status.value} -> {target.value} 不是合法转移"
            )
        self.status = target

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "proposal": self.proposal,
            "approval": self.approval,
            "executed": list(self.executed),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Ticket":
        t = cls(id=d["id"], title=d["title"], status=TicketStatus(d["status"]))
        t.evidence = [Evidence(**e) for e in d["evidence"]]
        t.proposal = d.get("proposal")
        t.approval = d.get("approval")
        t.executed = list(d.get("executed", []))
        return t

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Ticket":
        return cls.from_dict(json.loads(s))


# 共享执行器语义：高风险动作必须审批后才能执行；幂等靠 executed 记录。
def execute_proposal(ticket: Ticket) -> list[str]:
    """按共享规则执行 ticket.proposal，返回执行记录。"""
    if ticket.proposal is None:
        raise ValueError("没有可执行的提案")
    proposal = ActionProposal.from_dict(ticket.proposal)
    if proposal.risk == "high" and ticket.approval != "approved":
        raise ApprovalRequiredError(
            f"高风险动作 {proposal.action} 必须先经审批（当前 approval={ticket.approval!r}）"
        )
    if proposal.action in ticket.executed:
        return ticket.executed  # 幂等：相同动作不重复执行
    ticket.executed.append(proposal.action)
    return ticket.executed
