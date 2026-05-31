"""Inbound prompt-injection detection middleware (observe-first).

Scans inbound chat messages for high-precision injection signals and records a
detection (counter + ``context.metadata`` flag + log line). Observe-only by
default: the *active* defenses are the prompt-layer refusal rules
(``grounding-rules.yaml``) and tool-output sanitization
(:class:`OutputSanitizationMiddleware`). This layer adds observability and the
signal the safety / red-team evals assert on. When
``GUARDRAILS_BLOCK_ON_INJECTION`` is set, detections are logged at WARNING so
they surface on dashboards.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from agent_framework._middleware import ChatContext, ChatMiddleware

from shared.config import settings
from shared.guardrails.sanitize import contains_injection_markers

logger = logging.getLogger(__name__)


class InjectionDetectionChatMiddleware(ChatMiddleware):
    """Flag inbound messages that carry prompt-injection signals."""

    def __init__(self) -> None:
        self.detections = 0

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if not settings.GUARDRAILS_ENABLED:
            await call_next()
            return

        if self._flagged(context):
            self.detections += 1
            meta = getattr(context, "metadata", None)
            if isinstance(meta, dict):
                meta["guardrail_injection_detected"] = True
            level = logging.WARNING if settings.GUARDRAILS_BLOCK_ON_INJECTION else logging.INFO
            logger.log(
                level,
                "guardrails.injection_detected blocking=%s",
                settings.GUARDRAILS_BLOCK_ON_INJECTION,
            )

        await call_next()

    @staticmethod
    def _flagged(context: ChatContext) -> bool:
        for message in getattr(context, "messages", None) or []:
            for content in getattr(message, "contents", None) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str) and contains_injection_markers(text):
                    return True
        return False
