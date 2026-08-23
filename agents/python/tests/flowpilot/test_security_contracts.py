"""FlowPilot 安全合同：替代已删除电商工具的门禁测试。"""

from __future__ import annotations

import uuid

import pytest

from flowpilot.domain.executor import ACTION_CATALOG, ApprovalRequiredError, RiskLevel, assert_executable
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.domain.rbac import Actor, PermissionDeniedError, Role


def _proposal(action: str, params: dict[str, str]) -> ActionProposal:
    return ActionProposal(
        id=str(uuid.uuid4()),
        ticket_id="ticket-security-contract",
        action=action,
        params=params,
        evidence_ids=["evidence-security-contract"],
        risk=ACTION_CATALOG[action][0].value,
        created_by="flowpilot-handler",
        created_at=utc_now_iso(),
    )


def test_every_high_risk_catalog_action_requires_approval() -> None:
    for action, (risk, required, _allowed) in ACTION_CATALOG.items():
        if risk is not RiskLevel.HIGH:
            continue
        with pytest.raises(ApprovalRequiredError):
            assert_executable(
                _proposal(action, {key: "scoped" for key in required}),
                approved=False,
                already_executed=False,
            )


def test_role_matrix_separates_proposal_approval_and_execution() -> None:
    with pytest.raises(PermissionDeniedError):
        Actor("submitter", Role.SUBMITTER).check("proposal.create")
    with pytest.raises(PermissionDeniedError):
        Actor("handler", Role.HANDLER).check("proposal.approve")
    with pytest.raises(PermissionDeniedError):
        Actor("approver", Role.APPROVER).check("execution.run")
    Actor("service", Role.SERVICE).check("execution.run")
