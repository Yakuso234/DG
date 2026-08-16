"""RBAC：提交人、处理人、审批人、管理员与服务身份。

Phase 1 只做确定性权限检查（角色 × 动作矩阵）。JWT 身份验证在 Phase 2
接入（复用上游 shared/auth.py 的中间件骨架），此处不引入外部依赖。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from flowpilot.domain.status import TicketStatus


class Role(str, enum.Enum):
    SUBMITTER = "submitter"  # 提交人：建单、补充描述、查看自己的工单
    HANDLER = "handler"  # 处理人：调查、加证据、状态转移、建提案
    APPROVER = "approver"  # 审批人：审批决策，不能自己执行
    ADMIN = "admin"  # 管理员：全部 + 转派
    SERVICE = "service"  # 服务身份：执行器与系统动作，不参与审批


class PermissionDeniedError(PermissionError):
    def __init__(self, role: Role, action: str, reason: str) -> None:
        self.role = role
        self.action = action
        self.reason = reason
        super().__init__(f"{role.value} 无权执行 {action}: {reason}")


# 角色 × 动作 权限矩阵（确定性，不依赖 LLM 判断）
_ROLE_ACTIONS: dict[Role, frozenset[str]] = {
    Role.SUBMITTER: frozenset({"ticket.create", "ticket.view_own", "ticket.comment"}),
    Role.HANDLER: frozenset(
        {
            "ticket.view_any",
            "ticket.transition",
            "ticket.assign",
            "evidence.create",
            "proposal.create",
        }
    ),
    Role.APPROVER: frozenset({"ticket.view_any", "proposal.approve", "approval.list"}),
    Role.ADMIN: frozenset(
        {
            "ticket.view_any",
            "ticket.transition",
            "ticket.assign",
            "evidence.create",
            "proposal.create",
            "proposal.approve",
            "audit.read",
            "approval.list",
        }
    ),
    Role.SERVICE: frozenset({"ticket.view_any", "ticket.transition", "execution.run", "audit.write"}),
}


def check_permission(role: Role, action: str) -> None:
    """校验角色是否允许执行某动作，越权即抛 PermissionDeniedError。"""
    allowed = _ROLE_ACTIONS[role]
    if action not in allowed:
        raise PermissionDeniedError(role, action, "不在角色权限矩阵内")


@dataclass(frozen=True)
class Actor:
    """操作者身份：主体 id + 角色。所有写操作都必须携带。"""

    id: str
    role: Role

    def check(self, action: str) -> None:
        check_permission(self.role, action)


def can_transition_to(role: Role, target: TicketStatus) -> bool:
    """状态转移的角色约束：审批人不能直接推到 EXECUTING（只能通过审批决议）。"""
    if role in (Role.HANDLER, Role.ADMIN):
        return target in {
            TicketStatus.TRIAGED,
            TicketStatus.INVESTIGATING,
            TicketStatus.PROPOSED,
            TicketStatus.WAITING_APPROVAL,
            TicketStatus.ESCALATED,
            TicketStatus.FAILED,
        }
    if role is Role.SERVICE:
        return target in {TicketStatus.EXECUTING, TicketStatus.RESOLVED, TicketStatus.FAILED}
    return False


def actor_from_headers(headers: dict[str, Any]) -> Actor:
    """从请求头构造 Actor（Phase 1 简化身份传递；Phase 2 换 JWT 中间件）。"""
    actor_id = str(headers.get("x-user-id") or headers.get("x-agent-id") or "")
    role_raw = str(headers.get("x-user-role") or headers.get("x-agent-role") or "")
    if not actor_id:
        raise PermissionDeniedError(Role.SUBMITTER, "identity", "缺少 x-user-id")
    try:
        role = Role(role_raw)
    except ValueError as exc:
        raise PermissionDeniedError(Role.SUBMITTER, "identity", f"未知角色 {role_raw!r}") from exc
    return Actor(id=actor_id, role=role)
