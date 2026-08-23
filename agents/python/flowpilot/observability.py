"""请求级 TraceId：为日志、MCP/SW 调用和后续 OTel 导出提供同一关联键。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

TRACE_ID_HEADER = "X-Trace-Id"
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_current_trace_id: ContextVar[str] = ContextVar("flowpilot_trace_id", default="")


def is_valid_trace_id(value: str) -> bool:
    return bool(_TRACE_ID_PATTERN.fullmatch(value))


def new_trace_id() -> str:
    return f"fp-{uuid.uuid4().hex[:16]}"


def current_trace_id() -> str:
    return _current_trace_id.get()


def set_trace_id(value: str) -> None:
    if not is_valid_trace_id(value):
        raise ValueError("TraceId 只能包含字母、数字、点、下划线、冒号或连字符，且长度为 1-128")
    _current_trace_id.set(value)


def _tracer():
    from opentelemetry import trace

    return trace.get_tracer("flowpilot")


@contextmanager
def flowpilot_span(name: str, attributes: Mapping[str, Any] | None = None):
    """创建不含 Prompt/Evidence 正文的业务 span；未配置 SDK 时自动退化为 no-op。"""
    from opentelemetry import trace

    safe_attributes = {key: value for key, value in (attributes or {}).items() if value is not None}
    if trace_id := current_trace_id():
        safe_attributes.setdefault("flowpilot.trace_id", trace_id)
    with _tracer().start_as_current_span(name, attributes=safe_attributes) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
            raise


def traced_agent_step(step: str) -> Callable:
    """为 LangGraph 逻辑 Agent 节点增加统一、低敏属性。"""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(state: Mapping[str, Any], *args: Any, **kwargs: Any) -> Any:
            with flowpilot_span(
                f"flowpilot.agent.{step}",
                {
                    "flowpilot.agent.step": step,
                    "flowpilot.ticket.id": state.get("ticket_id"),
                    "flowpilot.creator.id": state.get("creator_id"),
                    "flowpilot.video.id": state.get("video_id"),
                },
            ):
                return await fn(state, *args, **kwargs)

        return wrapper

    return decorator


def traced_operation(name: str) -> Callable:
    """为工作流服务方法增加 span，只提取稳定业务 ID，不记录请求正文。"""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with flowpilot_span(
                name,
                {
                    "flowpilot.ticket.id": kwargs.get("ticket_id"),
                    "flowpilot.proposal.id": kwargs.get("proposal_id")
                    or (args[2] if len(args) > 2 and isinstance(args[2], str) else None),
                    "flowpilot.thread.id": kwargs.get("thread_id"),
                },
            ):
                return await fn(*args, **kwargs)

        return wrapper

    return decorator
