"""Tool-output sanitization middleware (Track A — stored-injection defense).

Runs after each tool executes and rewrites ``context.result`` in place for the
allowlisted tools whose results carry user-generated content, so adversarial
instructions embedded in reviews / descriptions / order notes reach the model
as inert data. MAF's ``FunctionInvocationContext.result`` is explicitly
documented as settable after ``call_next()`` to override the result.

No-op when guardrails or output sanitization are disabled. On an unexpected
error it logs and (fail-open) returns the raw result, unless
``GUARDRAILS_FAIL_OPEN`` is False, in which case it re-raises.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from agent_framework._middleware import FunctionInvocationContext, FunctionMiddleware

from shared.config import settings
from shared.guardrails.config import SANITIZE_TOOLS
from shared.guardrails.sanitize import neutralize_value

logger = logging.getLogger(__name__)


class OutputSanitizationMiddleware(FunctionMiddleware):
    """Neutralize stored / indirect prompt injection in tool outputs."""

    def __init__(self, tools: dict[str, set[str] | None] | None = None) -> None:
        self.tools = tools if tools is not None else SANITIZE_TOOLS
        self.sanitized = 0

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        await call_next()

        if not (settings.GUARDRAILS_ENABLED and settings.GUARDRAILS_OUTPUT_SANITIZATION):
            return

        fn = getattr(context, "function", None)
        name = getattr(fn, "name", None) or getattr(fn, "__name__", None)
        if name not in self.tools:
            return

        original = getattr(context, "result", None)
        if original is None:
            return

        try:
            cleaned = neutralize_value(original, fields=self.tools[name])
        except Exception:
            logger.exception("guardrails.output_sanitize_failed tool=%s", name)
            if settings.GUARDRAILS_FAIL_OPEN:
                return
            raise

        if cleaned != original:
            self.sanitized += 1
            logger.info("guardrails.output_sanitized tool=%s", name)
        context.result = cleaned
