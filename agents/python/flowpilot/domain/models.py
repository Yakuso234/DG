"""工单域数据对象（纯 dataclass，可 JSON 序列化）。

字段设计对应路线图 2.2 核心数据对象的最低字段要求。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from flowpilot.domain.status import TicketStatus


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Evidence:
    """工具产出证据：必须带来源、时间与引用，不允许匿名证据。"""

    id: str
    ticket_id: str
    tool: str
    source: str  # MCP 服务名
    data: dict[str, Any]
    collected_at: str  # ISO 8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionProposal:
    """结构化处置计划：动作、参数、证据引用、风险级别。

    由 Resolution Agent 生成，Risk Reviewer 复核；Phase 1 确定性版本由
    领域代码构造（无 LLM 路径），Phase 3 起由 Agent 产出并经过相同校验。
    """

    id: str
    ticket_id: str
    action: str
    params: dict[str, Any]
    evidence_ids: list[str]
    risk: str  # RiskLevel.LOW | RiskLevel.HIGH
    created_by: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionProposal:
        return cls(**d)


@dataclass(frozen=True)
class Approval:
    """审批记录：一个提案的全部决策历史（含版本）。"""

    id: str
    proposal_id: str
    ticket_id: str
    approver: str
    decision: str  # approved | denied | modified
    modified_params: dict[str, Any] | None
    note: str
    decided_at: str
    version: int  # 从 1 开始递增；并发冲突靠 proposal 状态 + 行锁拒绝

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionRecord:
    """受控执行记录：幂等键唯一，审计可追溯。"""

    id: str
    proposal_id: str
    ticket_id: str
    idempotency_key: str
    status: str  # pending | running | succeeded | failed
    attempts: int
    result: dict[str, Any] | None
    started_at: str | None
    finished_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditEvent:
    """审计事件：任何业务写操作都必须产生一条。"""

    id: str
    entity: str  # ticket | evidence | proposal | approval | execution
    entity_id: str
    action: str
    actor: str
    actor_role: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Ticket:
    """工单聚合根。version 用于乐观锁（并发状态转移检测）。"""

    id: str
    title: str
    description: str
    priority: int  # 1 最低 ~ 5 最高
    status: TicketStatus = TicketStatus.NEW
    submitter: str = ""
    assignee: str | None = None
    version: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def transition(self, target: TicketStatus) -> None:
        from flowpilot.domain.status import assert_legal_transition

        assert_legal_transition(self.status, target)
        self.status = target
        self.version += 1
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Ticket:
        return cls(
            id=d["id"],
            title=d["title"],
            description=d["description"],
            priority=int(d["priority"]),
            status=TicketStatus(d["status"]),
            submitter=d.get("submitter", ""),
            assignee=d.get("assignee"),
            version=int(d.get("version", 0)),
            created_at=d.get("created_at") or utc_now_iso(),
            updated_at=d.get("updated_at") or utc_now_iso(),
        )
