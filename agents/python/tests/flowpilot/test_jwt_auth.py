from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from flowpilot.api.main import build_app
from flowpilot.auth import FlowPilotAuthConfig

_SECRET = "flowpilot-test-secret-0123456789-abcdefghijklmnopqrstuvwxyz"
_ISSUER = "https://auth.flowpilot.test"
_AUDIENCE = "flowpilot-api"


def _config() -> FlowPilotAuthConfig:
    return FlowPilotAuthConfig("jwt-local", _SECRET, _ISSUER, _AUDIENCE)


def _token(*, role: str = "submitter", user_id: str = "u-jwt", **extra) -> str:
    payload = {
        "sub": "candidate@example.com",
        "user_id": user_id,
        "role": role,
        "type": "access",
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **extra,
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


@pytest.fixture
async def jwt_client(postgres_pool, clean_db):
    app = build_app(postgres_pool, auth_config=_config())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_jwt_local_mode_uses_signed_claims_not_spoofable_headers(jwt_client: AsyncClient) -> None:
    response = await jwt_client.post(
        "/api/tickets",
        headers={
            "Authorization": f"Bearer {_token(role='submitter', user_id='trusted-user')}",
            "x-user-id": "spoofed-admin",
            "x-user-role": "admin",
        },
        json={"title": "JWT protected ticket"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["submitter"] == "trusted-user"


async def test_jwt_local_mode_rejects_missing_tampered_and_wrong_role_tokens(jwt_client: AsyncClient) -> None:
    missing = await jwt_client.post("/api/tickets", json={"title": "x"})
    assert missing.status_code == 401

    tampered = await jwt_client.post(
        "/api/tickets", headers={"Authorization": f"Bearer {_token()}x"}, json={"title": "x"}
    )
    assert tampered.status_code == 401

    wrong_role = await jwt_client.post(
        "/api/tickets", headers={"Authorization": f"Bearer {_token(role='customer')}"}, json={"title": "x"}
    )
    assert wrong_role.status_code == 401


def test_jwt_local_mode_requires_strong_complete_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLOWPILOT_AUTH_MODE", "jwt-local")
    monkeypatch.setenv("FLOWPILOT_JWT_SECRET", "short")
    monkeypatch.delenv("FLOWPILOT_JWT_ISSUER", raising=False)
    monkeypatch.delenv("FLOWPILOT_JWT_AUDIENCE", raising=False)

    with pytest.raises(ValueError, match="至少 32 字节"):
        FlowPilotAuthConfig.from_env()
