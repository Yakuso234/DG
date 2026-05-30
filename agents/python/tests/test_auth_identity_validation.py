"""Tests for forwarded-identity validation on the inter-agent path (Track A5).

Pure helper tests plus a Starlette integration test exercising the
observe-vs-strict behavior. No LLM; no DB.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from shared.auth import AgentAuthMiddleware, _identity_anomaly
from shared.config import settings


def test_identity_anomaly_accepts_valid() -> None:
    assert _identity_anomaly("alice@example.com", "customer") is None
    assert _identity_anomaly("alice@example.com", "seller") is None
    assert _identity_anomaly("alice@example.com", "admin") is None
    assert _identity_anomaly("system", "system") is None


def test_identity_anomaly_flags_unknown_role() -> None:
    assert _identity_anomaly("alice@example.com", "superadmin") == "unknown_role:superadmin"


def test_identity_anomaly_flags_malformed_email() -> None:
    assert _identity_anomaly("not-an-email", "customer") == "malformed_email"


async def _ok(request):
    return JSONResponse({"ok": True})


def _client() -> TestClient:
    app = Starlette(routes=[Route("/x", _ok, methods=["POST"])])
    app.add_middleware(AgentAuthMiddleware, agent_name="test")
    return TestClient(app)


def _headers(role: str = "customer", email: str = "alice@example.com") -> dict:
    return {
        "x-agent-secret": settings.AGENT_SHARED_SECRET,
        "x-user-email": email,
        "x-user-role": role,
    }


def test_valid_forwarded_identity_passes() -> None:
    assert _client().post("/x", headers=_headers()).status_code == 200


def test_spoofed_role_allowed_when_not_strict(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", False)
    resp = _client().post("/x", headers=_headers(role="superadmin"))
    assert resp.status_code == 200  # observe-only: logged, not blocked


def test_spoofed_role_rejected_when_strict(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", True)
    resp = _client().post("/x", headers=_headers(role="superadmin"))
    assert resp.status_code == 401


def test_wrong_agent_secret_rejected() -> None:
    resp = _client().post("/x", headers={"x-agent-secret": "wrong-secret"})
    assert resp.status_code == 401
