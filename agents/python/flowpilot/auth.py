"""FlowPilot API 的可选 JWT 身份边界。

默认 headers 模式只服务本地 Demo；jwt-local 模式要求经过签名、issuer 和
audience 校验的 HS256 access token，再映射到领域 Actor。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import jwt

from flowpilot.domain.rbac import Actor, Role


class FlowPilotAuthError(PermissionError):
    """调用方未提供或提供了不可接受的认证主体。"""


@dataclass(frozen=True)
class FlowPilotAuthConfig:
    mode: str = "headers"
    jwt_secret: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""

    @classmethod
    def from_env(cls) -> FlowPilotAuthConfig:
        config = cls(
            mode=os.environ.get("FLOWPILOT_AUTH_MODE", "headers").strip().lower(),
            jwt_secret=os.environ.get("FLOWPILOT_JWT_SECRET", ""),
            jwt_issuer=os.environ.get("FLOWPILOT_JWT_ISSUER", ""),
            jwt_audience=os.environ.get("FLOWPILOT_JWT_AUDIENCE", ""),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"headers", "jwt-local"}:
            raise ValueError(f"FLOWPILOT_AUTH_MODE 只能是 headers 或 jwt-local，实际为 {self.mode!r}")
        if self.mode == "jwt-local":
            if len(self.jwt_secret.encode("utf-8")) < 32:
                raise ValueError("jwt-local 模式要求 FLOWPILOT_JWT_SECRET 至少 32 字节")
            if not self.jwt_issuer.strip() or not self.jwt_audience.strip():
                raise ValueError("jwt-local 模式要求 FLOWPILOT_JWT_ISSUER 和 FLOWPILOT_JWT_AUDIENCE")

    def actor_from_bearer(self, authorization: str | None) -> Actor:
        if self.mode != "jwt-local":
            raise RuntimeError("headers 模式不应调用 actor_from_bearer")
        if authorization is None or not authorization.startswith("Bearer "):
            raise FlowPilotAuthError("缺少 Bearer access token")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise FlowPilotAuthError("缺少 Bearer access token")
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                issuer=self.jwt_issuer,
                audience=self.jwt_audience,
                options={"require": ["exp", "sub", "role", "type"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise FlowPilotAuthError("access token 已过期") from exc
        except jwt.PyJWTError as exc:
            raise FlowPilotAuthError("access token 无效") from exc
        if payload.get("type") != "access":
            raise FlowPilotAuthError("token type 必须为 access")
        actor_id = payload.get("user_id") or payload.get("sub")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise FlowPilotAuthError("access token 缺少稳定主体 ID")
        try:
            role = Role(str(payload["role"]))
        except (KeyError, ValueError) as exc:
            raise FlowPilotAuthError("access token 包含未授权的 FlowPilot role") from exc
        return Actor(actor_id, role)
