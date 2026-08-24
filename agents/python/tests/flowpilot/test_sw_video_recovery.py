from __future__ import annotations

import uuid

import httpx
import pytest

from flowpilot.action_runner import ActionOutcomeUnknownError
from flowpilot.db import TicketRepo
from flowpilot.domain.executor import SW_VIDEO_RECOVERY_ACTION, ParamValidationError, next_idempotency_key
from flowpilot.domain.models import ActionProposal, utc_now_iso
from flowpilot.domain.rbac import Actor, Role
from flowpilot.sw_video_recovery import (
    SwVideoRecoveryActionRunner,
    SwVideoRecoveryAuthError,
    SwVideoRecoveryNotFoundError,
    SwVideoRecoveryRejectedError,
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


def _payload(proposal: ActionProposal, *, status: str = "ACCEPTED", replayed: bool = False) -> dict:
    return {
        "code": 1,
        "msg": "success",
        "data": {
            "recoveryId": "recovery-1",
            "videoId": proposal.params["video_id"],
            "idempotencyKey": next_idempotency_key(proposal.id, proposal.action),
            "status": status,
            "reason": "PRECONDITION_NOT_MET" if status == "REJECTED" else None,
            "outboxId": "outbox-1" if status == "ACCEPTED" else None,
            "traceId": proposal.params["trace_id"],
            "requestedBy": "flowpilot",
            "replayed": replayed,
            "createdAt": "2026-08-24T10:00:00",
        },
    }


async def test_recovery_runner_posts_persistent_receipt_with_identity_trace_and_idempotency() -> None:
    requests: list[httpx.Request] = []
    proposal = _proposal()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload(proposal))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(
            base_url="http://sw-video", service_token="service-secret", service_name="flowpilot", client=client
        )
        result = await runner.run(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/video/api/private/processing/9/recover-expired"
    assert requests[0].headers["authorization"] == "Bearer service-secret"
    assert requests[0].headers["idempotency-key"] == next_idempotency_key(proposal.id, proposal.action)
    assert result["business_result"]["outbox_id"] == "outbox-1"
    assert "service-secret" not in str(result)


async def test_recovery_runner_rejected_receipt_is_explicit_failure() -> None:
    proposal = _proposal()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=_payload(proposal, status="REJECTED")))
    async with httpx.AsyncClient(transport=transport) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(SwVideoRecoveryRejectedError, match="PRECONDITION_NOT_MET"):
            await runner.run(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))


@pytest.mark.parametrize("status", [401, 403, 404, 409])
async def test_recovery_runner_maps_auth_route_and_contract_failures(status: int) -> None:
    proposal = _proposal()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(status))) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        expected = (
            SwVideoRecoveryAuthError
            if status in {401, 403}
            else (SwVideoRecoveryNotFoundError if status == 404 else SwVideoRecoveryRejectedError)
        )
        with pytest.raises(expected):
            await runner.run(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))


async def test_recovery_runner_treats_timeout_and_5xx_as_unknown() -> None:
    proposal = _proposal()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(ActionOutcomeUnknownError):
            await runner.run(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))


async def test_recovery_runner_can_inject_response_loss_only_after_accepted_once() -> None:
    proposal = _proposal()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload(proposal))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(
            base_url="http://sw-video", service_token="token", client=client, fault_after_accepted_once=True
        )
        key = next_idempotency_key(proposal.id, proposal.action)
        with pytest.raises(ActionOutcomeUnknownError, match="SW 已 ACCEPTED"):
            await runner.run(proposal, idempotency_key=key)
        accepted = await runner.run(proposal, idempotency_key=key)

    assert len(requests) == 2
    assert accepted["business_result"]["outbox_id"] == "outbox-1"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(503))) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        with pytest.raises(ActionOutcomeUnknownError):
            await runner.run(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))


async def test_recovery_reconcile_gets_accepted_receipt_or_reposts_same_key_after_404() -> None:
    proposal = _proposal()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json=_payload(proposal, replayed=True))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        outcome = await runner.reconcile(proposal, idempotency_key=next_idempotency_key(proposal.id, proposal.action))

    assert methods == ["GET", "POST"]
    assert outcome.status == "succeeded"
    assert outcome.result["business_result"]["replayed"] is True


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
            await runner.run(invalid, idempotency_key=next_idempotency_key(proposal.id, proposal.action))


async def test_postgres_execution_persists_receipt_and_deduplicates_side_effect(postgres_pool, clean_db) -> None:
    requests: list[httpx.Request] = []
    ticket = await TicketRepo(postgres_pool).create_ticket(
        Actor("u-submit", Role.SUBMITTER), "SW 视频处理卡住", "租约已过期"
    )
    proposal = _proposal(ticket_id=ticket.id, video_id=901)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload(proposal))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = SwVideoRecoveryActionRunner(base_url="http://sw-video", service_token="token", client=client)
        repo = TicketRepo(postgres_pool, runner)
        await repo.create_proposal(Actor("flowpilot-resolution-agent", Role.HANDLER), proposal)
        await repo.approve_proposal(Actor("u-approver", Role.APPROVER), proposal.id, "approved")
        first = await repo.execute_proposal(Actor("flowpilot-action-executor", Role.SERVICE), proposal.id)
        repeated = await repo.execute_proposal(Actor("flowpilot-action-executor", Role.SERVICE), proposal.id)

    assert first.status == "succeeded"
    assert repeated.id == first.id
    assert first.result is not None and first.result["business_result"]["outbox_id"] == "outbox-1"
    assert len(requests) == 1
