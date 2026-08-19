"""模拟业务系统：Phase 1 的确定性业务状态与故障注入。

用途：
- 让 FlowPilot 脱离 SW 环境仍可演示完整闭环（无 LLM、无外部依赖）。
- Phase 2 的 `mock-business-mcp` 将把本模块的语义包装成 MCP 工具；
  这里的纯 Python 实现是确定性语义的唯一来源，MCP 层只做协议转换。

能力（对应路线图 Phase 1 任务 6）：
- 状态查询：确定性返回（同输入同输出，无随机数）。
- 可恢复异常：注入 flapping 后首次查询抛 TransientError，重试成功。
- 需审批写操作：restart_pipeline 记录到操作日志，可校验调用方是否持有
  批准（Phase 1 由调用方（repo.executor）保证；Phase 4 由 Approval 记录驱动）。
- 故障注入：timeout / partial_failure / flapping 三类，可注入、可清除。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


class TransientError(RuntimeError):
    """可恢复异常：重试可成功。"""


class FaultInjectedError(RuntimeError):
    """注入故障：超时/部分失败。"""


@dataclass
class BusinessEntity:
    id: str
    state: str  # processing | done | failed
    events: list[dict] = field(default_factory=list)
    faults: set[str] = field(default_factory=set)
    _flap_first_call_done: bool = False


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MockBusinessSystem:
    """确定性内存业务系统；故障注入只影响本实例，不影响真实业务。"""

    def __init__(self) -> None:
        self._entities: dict[str, BusinessEntity] = {}
        self.operations: list[dict] = []

    def register(self, entity_id: str, state: str = "processing") -> None:
        self._entities[entity_id] = BusinessEntity(id=entity_id, state=state)

    def ensure_entity(self, entity_id: str, state: str = "processing") -> None:
        """为确定性 Demo 准备业务实体；已存在时不覆盖其故障或事件。"""
        if entity_id not in self._entities:
            self.register(entity_id, state=state)

    def _entity(self, entity_id: str) -> BusinessEntity:
        if entity_id not in self._entities:
            raise KeyError(f"业务实体 {entity_id} 不存在")
        return self._entities[entity_id]

    def get_status(self, entity_id: str) -> dict:
        """状态查询：确定性输出（无随机、无时间戳差异）。"""
        entity = self._entity(entity_id)
        if "timeout" in entity.faults:
            raise FaultInjectedError(f"fault=timeout on {entity_id}")
        if "flapping" in entity.faults:
            if not entity._flap_first_call_done:
                entity._flap_first_call_done = True
                raise TransientError(f"transient failure on {entity_id}（重试可恢复）")
            entity._flap_first_call_done = False
        if "partial_failure" in entity.faults:
            return {"id": entity.id, "state": entity.state, "partial": True, "detail": "部分组件不可用"}
        return {"id": entity.id, "state": entity.state, "events": list(entity.events)}

    def restart_pipeline(self, entity_id: str, force: bool = False) -> dict:
        """需审批写操作：记录到操作日志，返回确定性结果。

        真实系统中高危写操作必须经审批；本模拟系统只保证"写操作有记录、
        可审计"，审批门由 FlowPilot 的 executor/approval 链路强制。
        """
        entity = self._entity(entity_id)
        if "timeout" in entity.faults:
            raise FaultInjectedError(f"fault=timeout on {entity_id}")
        record = {
            "op": "restart_pipeline",
            "entity_id": entity_id,
            "force": force,
            "at": utc_now_iso(),
        }
        self.operations.append(record)
        entity.state = "processing"
        entity.events.append({"type": "restart", "at": record["at"]})
        return {"ok": True, "entity_id": entity_id, "state": entity.state}

    def add_note(self, entity_id: str, content: str) -> dict:
        """记录低风险备注，供执行器测试完整的写操作适配路径。"""
        entity = self._entity(entity_id)
        record = {"op": "add_note", "entity_id": entity_id, "content": content, "at": utc_now_iso()}
        self.operations.append(record)
        entity.events.append({"type": "note", "content": content, "at": record["at"]})
        return {"ok": True, "entity_id": entity_id, "recorded": True}

    def inject_fault(self, entity_id: str, fault: str) -> None:
        if fault not in ("timeout", "partial_failure", "flapping"):
            raise ValueError(f"未知故障类型 {fault!r}")
        self._entity(entity_id).faults.add(fault)

    def clear_faults(self, entity_id: str) -> None:
        self._entity(entity_id).faults.clear()
