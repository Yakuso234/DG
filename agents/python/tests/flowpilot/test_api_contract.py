"""API 层 HTTP 契约测试：无 LLM 闭环 + 越权/非法转移/审批门/审计。

使用 httpx ASGITransport 直连 build_app(pool)，池来自 testcontainers
Postgres（复用上游 conftest 的 postgres_pool / clean_db fixture）。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from flowpilot.api import build_app

H = lambda uid: {"x-user-id": uid}  # noqa: E731
SUB = {**H("u-sub"), "x-user-role": "submitter"}
HANDLER = {**H("u-handler"), "x-user-role": "handler"}
APPROVER = {**H("u-approver"), "x-user-role": "approver"}
SERVICE = {**H("svc-executor"), "x-user-role": "service"}
ADMIN = {**H("u-admin"), "x-user-role": "admin"}


@pytest.fixture
async def client(postgres_pool, clean_db):
    app = build_app(postgres_pool)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_ticket(client: AsyncClient, title: str = "视频处理中") -> dict:
    resp = await client.post("/api/tickets", json={"title": title, "description": "上传后长时间处理中"}, headers=SUB)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _walk_to_approval(client: AsyncClient, ticket_id: str, action: str = "restart_pipeline") -> dict:
    for target in ("TRIAGED", "INVESTIGATING"):
        resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": target}, headers=HANDLER)
        assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/tickets/{ticket_id}/proposals",
        json={"action": action, "params": {"ticket_id": ticket_id}, "risk": "high"},
        headers=HANDLER,
    )
    assert resp.status_code == 201, resp.text
    proposal = resp.json()
    for target in ("PROPOSED", "WAITING_APPROVAL"):
        resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": target}, headers=HANDLER)
        assert resp.status_code == 200, resp.text
    return proposal


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "flowpilot-api"


async def test_api_propagates_valid_trace_id_and_rejects_invalid_input(client: AsyncClient) -> None:
    response = await client.post(
        "/api/tickets",
        json={"title": "trace"},
        headers={**SUB, "X-Trace-Id": "trace-api-1"},
    )
    assert response.status_code == 201
    assert response.headers["X-Trace-Id"] == "trace-api-1"

    rejected = await client.get("/health", headers={"X-Trace-Id": "trace with spaces"})
    assert rejected.status_code == 400
    assert rejected.headers["X-Trace-Id"].startswith("fp-")


async def test_missing_identity_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/tickets", json={"title": "x"})
    assert resp.status_code == 403


async def test_http_closed_loop(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    ticket_id = ticket["id"]
    assert ticket["status"] == "NEW"

    proposal = await _walk_to_approval(client, ticket_id)
    resp = await client.post(
        f"/api/proposals/{proposal['id']}/approvals",
        json={"decision": "approved", "note": "确认重启安全"},
        headers=APPROVER,
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "approved"

    resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": "EXECUTING"}, headers=SERVICE)
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/proposals/{proposal['id']}/execute", headers=SERVICE)
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"

    resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": "RESOLVED"}, headers=SERVICE)
    assert resp.status_code == 200, resp.text

    got = await client.get(f"/api/tickets/{ticket_id}", headers=ADMIN)
    assert got.json()["status"] == "RESOLVED"


async def test_high_risk_execute_without_approval_409(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    proposal = await _walk_to_approval(client, ticket["id"], action="delete_data")
    resp = await client.post(f"/api/proposals/{proposal['id']}/execute", headers=SERVICE)
    assert resp.status_code == 409
    assert "ApprovalRequiredError" in resp.json()["detail"]


async def test_illegal_transition_409(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    # 先合法推进到 TRIAGED
    resp = await client.post(f"/api/tickets/{ticket['id']}/transitions", json={"target": "TRIAGED"}, headers=HANDLER)
    assert resp.status_code == 200
    # 自环转移：角色允许目标（handler 可转 TRIAGED），但状态机拒绝 → 409
    resp = await client.post(f"/api/tickets/{ticket['id']}/transitions", json={"target": "TRIAGED"}, headers=HANDLER)
    assert resp.status_code == 409
    assert "IllegalTransitionError" in resp.json()["detail"]


async def test_transition_preconditions_are_enforced_at_api_boundary(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    ticket_id = ticket["id"]
    for target in ("TRIAGED", "INVESTIGATING"):
        resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": target}, headers=HANDLER)
        assert resp.status_code == 200, resp.text

    resp = await client.post(f"/api/tickets/{ticket_id}/transitions", json={"target": "PROPOSED"}, headers=HANDLER)
    assert resp.status_code == 409
    assert "StatePreconditionError" in resp.json()["detail"]


async def test_unauthorized_transition_403(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    resp = await client.post(f"/api/tickets/{ticket['id']}/transitions", json={"target": "TRIAGED"}, headers=SUB)
    assert resp.status_code == 403


async def test_evidence_roundtrip(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    resp = await client.post(
        f"/api/tickets/{ticket['id']}/evidence",
        json={"tool": "get_ticket_status", "source": "mock-business-mcp", "data": {"state": "processing"}},
        headers=HANDLER,
    )
    assert resp.status_code == 201
    items = await client.get(f"/api/tickets/{ticket['id']}/evidence", headers=ADMIN)
    assert items.status_code == 200
    assert len(items.json()) == 1
    assert items.json()[0]["source"] == "mock-business-mcp"


async def test_audit_endpoint(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    resp = await client.get(f"/api/audit/ticket/{ticket['id']}", headers=ADMIN)
    assert resp.status_code == 200
    actions = {e["action"] for e in resp.json()}
    assert "ticket.create" in actions


async def test_unknown_ticket_404(client: AsyncClient) -> None:
    resp = await client.get(f"/api/tickets/{uuid.uuid4()}", headers=HANDLER)
    assert resp.status_code == 404


async def test_invalid_param_contract_422(client: AsyncClient) -> None:
    ticket = await _make_ticket(client)
    resp = await client.post(
        f"/api/tickets/{ticket['id']}/proposals",
        json={"action": "restart_pipeline", "params": {"evil": True}, "risk": "high"},
        headers=HANDLER,
    )
    assert resp.status_code == 422
    assert "ParamValidationError" in resp.json()["detail"]
