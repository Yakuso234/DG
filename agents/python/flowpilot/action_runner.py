"""业务动作适配层：将受控 ActionProposal 映射为确定性业务调用。

Repository 只负责事务、审批、幂等记录与审计；任何外部副作用都必须在
事务提交后由本层执行，避免持有数据库锁等待网络/业务调用。P1 使用
MockBusinessSystem，P2 再以同一协议替换为 SW 的受限 HTTP 调用。
"""

from __future__ import annotations

from typing import Any, Protocol

from flowpilot.domain.models import ActionProposal
from flowpilot.mock_business import MockBusinessSystem


class BusinessActionRunner(Protocol):
    async def run(self, proposal: ActionProposal) -> dict[str, Any]:
        """执行已通过领域校验的结构化动作，或抛出可审计异常。"""


class UnsupportedBusinessActionError(RuntimeError):
    """当前业务适配器不支持该动作，禁止伪造成功结果。"""


class MockBusinessActionRunner:
    """P1 的确定性业务适配器，不依赖 LLM、网络或 SW。"""

    def __init__(self, business: MockBusinessSystem | None = None) -> None:
        self.business = business or MockBusinessSystem()

    async def run(self, proposal: ActionProposal) -> dict[str, Any]:
        entity_id = str(proposal.params["ticket_id"])
        self.business.ensure_entity(entity_id, state="processing")

        if proposal.action == "diagnose_status":
            result = self.business.get_status(entity_id)
        elif proposal.action == "restart_pipeline":
            result = self.business.restart_pipeline(entity_id, force=bool(proposal.params.get("force", False)))
        elif proposal.action == "add_note":
            result = self.business.add_note(entity_id, str(proposal.params["content"]))
        else:
            raise UnsupportedBusinessActionError(f"Mock 业务适配器不支持动作 {proposal.action!r}")

        return {"ok": True, "adapter": "mock-business", "action": proposal.action, "business_result": result}
