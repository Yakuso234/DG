"""工单状态机：唯一的合法转移表。

纯 Python 标准库，无 LLM、无框架依赖——Phase 1 验收要求确定性执行核心
在无 LLM、无 SW 环境下可独立运行。
"""

from __future__ import annotations

import enum


class TicketStatus(enum.StrEnum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    PROPOSED = "PROPOSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# 唯一合法转移表。任何代码路径（API、Agent、执行器）都必须引用此表，
# 不允许出现第二份转移定义。
LEGAL_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.NEW: frozenset({TicketStatus.TRIAGED}),
    TicketStatus.TRIAGED: frozenset({TicketStatus.INVESTIGATING, TicketStatus.ESCALATED}),
    TicketStatus.INVESTIGATING: frozenset({TicketStatus.PROPOSED, TicketStatus.ESCALATED, TicketStatus.FAILED}),
    TicketStatus.PROPOSED: frozenset({TicketStatus.WAITING_APPROVAL, TicketStatus.FAILED}),
    TicketStatus.WAITING_APPROVAL: frozenset({TicketStatus.EXECUTING, TicketStatus.ESCALATED, TicketStatus.FAILED}),
    TicketStatus.EXECUTING: frozenset({TicketStatus.RESOLVED, TicketStatus.FAILED}),
    TicketStatus.RESOLVED: frozenset(),
    TicketStatus.ESCALATED: frozenset(),
    TicketStatus.FAILED: frozenset(),
}


class IllegalTransitionError(ValueError):
    """非法状态转移：转移表之外的目标状态一律拒绝。"""

    def __init__(self, current: TicketStatus, target: TicketStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"{current.value} -> {target.value} 不是合法转移")


def assert_legal_transition(current: TicketStatus, target: TicketStatus) -> None:
    if target not in LEGAL_TRANSITIONS[current]:
        raise IllegalTransitionError(current, target)
