"""请求级 TraceId：为日志、MCP/SW 调用和后续 OTel 导出提供同一关联键。"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

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
