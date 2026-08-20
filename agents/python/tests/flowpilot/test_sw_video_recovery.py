from __future__ import annotations

import uuid

import httpx
import pytest

from flowpilot.action_runner import UnsupportedBusinessActionError
from flowpilot.db import TicketRepo
from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION, ParamValidationError, next_idempotency_key
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.domain.rbac import Actor, Role
from flowpilot.sw_video_recovery import (
    SwVideoRecoveryActionRunner,
    SwVideoRecoveryAuthError,
    SwVideoRecoveryNotFoundError,
    SwVideoRecoveryRejectedError,
    SwVideoRecoveryUpstreamError,
)


def _proposal(*, ticket_id: str = "ticket-1", video_id: int = 9) -> ActionProposal:
    return ActionProposal(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        action=SW_VIDEO_RECOVERY_ACTION,
        params={"ticket_id": ticket_id, "creator_id": 7, "video_id": video_id, "trace_id": "trace-recovery"},
        evidence_ids=[str(uuid.uuid4())],
        risk="high",
        created_by="flowpilot-resolution-agent",
        created_at=utc_now_iso(),
    )


async def test_recovery_runner_calls_exact_sw_contract_with_identity_trace_and_idempotency() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 1, "msg": "success", "data": True})

    proposal = _proposal()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(
            base_url="http://sw-video", service_token="service-secret", service_name="flowpilot", client=client
        )
        result = await runner.run(proposal)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/video/api/private/processing/9/recover-expired"
    assert request.headers["authorization"] == "Bearer service-secret"
    assert request.headers["x-flowpilot-service"] == "flowpilot"
    assert request.headers["x-trace-id"] == "trace-recovery"
    assert request.headers["idempotency-key"] == next_idempotency_key(proposal.id, proposal.action)
    assert result["business_result"]["recovery_created"] is True
    assert result["business_result"]["video_id"] == 9
    assert "service-secret" not in str(result)


def test_recovery_runner_fails_closed_without_service_identity() -> None:
    with pytest.raises(SwVideoRecoveryAuthError, match="拒绝无身份"):
        SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="")


async def test_recovery_runner_rejects_non_whitelisted_action_without_http_call() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"code": 1, "msg": "success", "data": True})

    proposal = _proposal()
    unsupported = ActionProposal(
        proposal.id,
        proposal.ticket_id,
        "restart_pipeline",
        {"ticket_id": proposal.ticket_id},
        proposal.evidence_ids,
        "high",
        proposal.created_by,
        proposal.created_at,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(UnsupportedBusinessActionError):
            await runner.run(unsupported)

    assert called is False


async def test_recovery_runner_treats_false_result_as_failed_side_effect() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"code": 1, "msg": "success", "data": False})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(SwVideoRecoveryRejectedError, match="原子校验未通过"):
            await runner.run(_proposal())


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, SwVideoRecoveryAuthError),
        (404, SwVideoRecoveryNotFoundError),
        (503, SwVideoRecoveryUpstreamError),
    ],
)
async def test_recovery_runner_maps_http_failures(status: int, error_type: type[Exception]) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status))
    async with httpx.AsyncClient(transport=transport) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(error_type):
            await runner.run(_proposal())


async def test_recovery_runner_maps_timeout_without_leaking_success() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(SwVideoRecoveryUpstreamError, match="超时"):
            await runner.run(_proposal())


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "msg": "rejected", "data": None},
        {"code": 1, "msg": "success", "data": {"recovered": True}},
    ],
)
async def test_recovery_runner_rejects_invalid_result_contract(payload: dict) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(SwVideoRecoveryUpstreamError):
            await runner.run(_proposal())


async def test_recovery_runner_validates_target_before_http_call() -> None:
    proposal = _proposal()
    invalid = ActionProposal(
        proposal.id,
        proposal.ticket_id,
        proposal.action,
        {**proposal.params, "video_id": True},
        proposal.evidence_ids,
        proposal.risk,
        proposal.created_by,
        proposal.created_at,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(ParamValidationError, match="正整数"):
            await runner.run(invalid)


async def test_postgres_execution_calls_sw_once_and_persists_idempotent_result(postgres_pool, clean_db) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 1, "msg": "success", "data": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        repo = TicketRepo(postgres_pool, runner)
        ticket = await repo.create_ticket(Actor("u-submit", Role.SUBMITTER), "SW 视频处理卡住", "租约已过期")
        proposal = _proposal(ticket_id=ticket.id, video_id=901)
        await repo.create_proposal(Actor("flowpilot-resolution-agent", Role.HANDLER), proposal)
        await repo.approve_proposal(Actor("u-approver", Role.APPROVER), proposal.id, "approved")

        first = await repo.execute_proposal(Actor("flowpilot-action-executor", Role.SERVICE), proposal.id)
        repeated = await repo.execute_proposal(Actor("flowpilot-action-executor", Role.SERVICE), proposal.id)

    assert first.status == "succeeded"
    assert repeated.id == first.id
    assert first.result is not None and first.result["adapter"] == "sw-video-recovery"
    assert first.result["business_result"]["video_id"] == 901
    assert len(requests) == 1


async def test_approval_cannot_change_evidence_bound_video_target(postgres_pool, clean_db) -> None:
    repo = TicketRepo(postgres_pool)
    ticket = await repo.create_ticket(Actor("u-submit", Role.SUBMITTER), "SW 视频处理卡住", "租约已过期")
    proposal = _proposal(ticket_id=ticket.id, video_id=901)
    await repo.create_proposal(Actor("flowpilot-resolution-agent", Role.HANDLER), proposal)

    with pytest.raises(ParamValidationError, match="不能改变执行范围"):
        await repo.approve_proposal(
            Actor("u-approver", Role.APPROVER),
            proposal.id,
            "modified",
            {**proposal.params, "video_id": 902},
        )
