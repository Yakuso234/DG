"""Request-scoped state via ContextVars.

Set by auth middleware, read by tools.
"""

from contextvars import ContextVar

current_user_email: ContextVar[str] = ContextVar("current_user_email", default="")
current_user_role: ContextVar[str] = ContextVar("current_user_role", default="")
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")
current_conversation_history: ContextVar[list] = ContextVar("current_conversation_history", default=[])

# Per-request agentic-timeline steps. None outside a request scope (so the
# tool-recording middleware is a no-op); a request sets it to a fresh list.
current_steps: ContextVar[list | None] = ContextVar("current_steps", default=None)
