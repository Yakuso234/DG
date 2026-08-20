"""受控执行核心：动作合同、参数校验、风险分级与幂等语义。

红线：执行器不接受自由文本命令；高风险动作必须经过审批（Phase 4 接入
持久化审批后由 approval 记录驱动，Phase 1 先由 proposal.risk 与审批状态
共同约束）。
"""

from __future__ import annotations

import enum
from typing import Any

from flowpilot.domain.models import ActionProposal


class RiskLevel(enum.StrEnum):
    LOW = "low"
    HIGH = "high"


class ParamValidationError(ValueError):
    """动作参数不符合合同。"""


class ExecutionError(RuntimeError):
    """执行被拒绝：未审批、幂等冲突或其他合同违反。"""


class ApprovalRequiredError(ExecutionError):
    """高风险动作未经批准即执行。"""


SW_VIDEO_RECOVERY_ACTION = "recover_expired_video_processing"


# 动作合同目录：action -> (风险级别, 必填参数, 允许参数)。
# 不在目录中的动作一律拒绝执行；目录在 Phase 4 由 Risk Reviewer 复核，
# 但始终由领域代码决定是否放行。
ACTION_CATALOG: dict[str, tuple[RiskLevel, frozenset[str], frozenset[str]]] = {
    # 只读诊断动作（低风险）
    "diagnose_status": (RiskLevel.LOW, frozenset({"ticket_id"}), frozenset({"ticket_id", "depth"})),
    # 可逆但有真实副作用的通用重启动作，仍按高风险要求审批。
    "restart_pipeline": (RiskLevel.HIGH, frozenset({"ticket_id"}), frozenset({"ticket_id", "force"})),
    # SW 视频恢复：只允许恢复租约已过期的处理任务，执行目标与追踪字段必须完整。
    SW_VIDEO_RECOVERY_ACTION: (
        RiskLevel.HIGH,
        frozenset({"ticket_id", "creator_id", "video_id", "trace_id"}),
        frozenset({"ticket_id", "creator_id", "video_id", "trace_id"}),
    ),
    # 不可逆动作：高危，必须审批
    "delete_data": (RiskLevel.HIGH, frozenset({"ticket_id"}), frozenset({"ticket_id", "cascade"})),
    # 写回工单备注（低风险）
    "add_note": (RiskLevel.LOW, frozenset({"ticket_id", "content"}), frozenset({"ticket_id", "content"})),
}

# 审批人可以修改处置选项，但不能把已经调查和复核过的提案转向另一个
# 工单或业务对象；需要换目标时必须重新调查并创建新提案。
EXECUTION_SCOPE_KEYS = frozenset({"ticket_id", "creator_id", "video_id", "trace_id"})


def validate_params(action: str, params: dict[str, Any]) -> None:
    """校验动作参数合同：未知动作、缺必填、多余参数一律拒绝。"""
    if action not in ACTION_CATALOG:
        raise ParamValidationError(f"未知动作 {action!r}，不在动作合同目录")
    _, required, allowed = ACTION_CATALOG[action]
    missing = required - params.keys()
    if missing:
        raise ParamValidationError(f"动作 {action} 缺少必填参数: {sorted(missing)}")
    extra = params.keys() - allowed
    if extra:
        raise ParamValidationError(f"动作 {action} 含非法参数: {sorted(extra)}")


def validate_modified_params(
    action: str,
    original_params: dict[str, Any],
    modified_params: dict[str, Any],
) -> None:
    """校验审批修改，并禁止改变已经由证据绑定的执行范围。"""
    validate_params(action, modified_params)
    changed_scope = sorted(
        key
        for key in EXECUTION_SCOPE_KEYS
        if key in original_params or key in modified_params
        if original_params.get(key) != modified_params.get(key)
    )
    if changed_scope:
        raise ParamValidationError(f"modified_params 不能改变执行范围参数: {changed_scope}")


def risk_of(action: str) -> RiskLevel:
    if action not in ACTION_CATALOG:
        raise ParamValidationError(f"未知动作 {action!r}")
    return ACTION_CATALOG[action][0]


def assert_executable(
    proposal: ActionProposal,
    *,
    approved: bool,
    already_executed: bool,
) -> None:
    """执行前置检查（幂等 + 审批 + 参数合同），全部通过才允许执行。"""
    if already_executed:
        raise ExecutionError(f"提案 {proposal.id} 已执行过（幂等键冲突）")
    validate_params(proposal.action, proposal.params)
    if risk_of(proposal.action) is RiskLevel.HIGH and not approved:
        raise ApprovalRequiredError(f"高风险动作 {proposal.action} 必须先经审批（proposal={proposal.id}）")


def next_idempotency_key(proposal_id: str, action: str) -> str:
    """幂等键：同一提案+动作在重试/恢复后必须得到同一个键。"""
    return f"{proposal_id}:{action}"
