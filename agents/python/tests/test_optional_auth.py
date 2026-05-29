"""Unit tests for the optional_auth dependency that powers the public storefront.

Anonymous (no token) → anonymous identity; valid token → real payload;
invalid token → 401. No DB/LLM needed.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from orchestrator.routes import optional_auth
from shared.jwt_utils import create_access_token


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    return Request({"type": "http", "headers": raw})


async def test_anonymous_when_no_authorization_header():
    user = await optional_auth(_request())
    assert user["anonymous"] is True
    assert user["role"] == "anonymous"
    assert user["sub"] == ""
    assert user["user_id"] == ""


async def test_returns_payload_for_valid_token():
    token = create_access_token("alice@example.com", "customer", "u-123")
    user = await optional_auth(_request({"Authorization": f"Bearer {token}"}))
    assert user.get("anonymous") is not True
    assert user["sub"] == "alice@example.com"
    assert user["role"] == "customer"
    assert user["user_id"] == "u-123"


async def test_rejects_present_but_invalid_token():
    with pytest.raises(HTTPException) as exc:
        await optional_auth(_request({"Authorization": "Bearer not-a-jwt"}))
    assert exc.value.status_code == 401
