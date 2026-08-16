"""确定性、无网络的 Fake Model。

行为规范见 SPIKE-001 合同第 4 节，两套栈必须一致：
  第 1 轮：返回工具调用 get_ticket_status(ticket_id="T-1001")。
  第 2 轮：返回 ActionProposal(action="restart_pipeline", risk="high")。
  之后：停止（返回 None）。

本模块不 import 任何网络库，也不读取环境变量中的真实 Key —— 任何网络调用
尝试都视为该场景失败（S4 用例另有 socket 守卫兜底）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.domain import ActionProposal

TOOL_NAME = "get_ticket_status"
TICKET_ID = "T-1001"


@dataclass(frozen=True)
class ToolCall:
    """FakeModel 产出的工具调用规格。"""

    name: str
    arguments: dict[str, Any]


class FakeModel:
    """无网络、确定性的模型替身。"""

    def __init__(self) -> None:
        self._round = 0

    @property
    def round(self) -> int:
        """已推进的轮数。"""
        return self._round

    def next(self) -> ToolCall | ActionProposal | None:
        """推进一轮；耗尽后返回 None。"""
        self._round += 1
        if self._round == 1:
            return ToolCall(TOOL_NAME, {"ticket_id": TICKET_ID})
        if self._round == 2:
            return ActionProposal(
                action="restart_pipeline",
                params={"ticket_id": TICKET_ID},
                evidence_tools=(TOOL_NAME,),
                risk="high",
            )
        return None
