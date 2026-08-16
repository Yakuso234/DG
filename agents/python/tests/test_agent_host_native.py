"""
Phase 7 Refactor 03 — MAF-native execution path tests.

Verifies:

- ``_history_as_maf_messages`` builds the right MAF ``Message`` list from
  the A2A history payload + current user message.
- ``_run_agent_native`` returns ``response.text`` from ``agent.run``.
- ``_run_agent_native_stream`` yields the text chunks from streaming
  updates.
- Real-LLM integration: running a live ``ChatClientAgent`` through the
  native helpers against Azure OpenAI produces a sensible answer.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

# Load the repo-root .env into os.environ so the integration tests see the
# live Azure / OpenAI credentials the rest of the suite uses.
# NOTE: tutorials/ was deleted in DG batch 1, so the old
# `tutorials._shared.maf_bootstrap` helper is replaced by the repo's own
# patch_maf (idempotent: only patches an empty agent_framework __init__)
# plus an inline .env loader.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from patch_maf import patch  # noqa: E402

patch()


def _load_root_env() -> None:
    env_file = pathlib.Path(__file__).resolve().parents[3] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_root_env()

from shared.agent_host import (  # noqa: E402
    _history_as_maf_messages,
    _rehydrate_history_from_session,
    _run_agent_native,
    _run_agent_native_stream,
)


# ─────────────────────── Pure helpers ───────────────────────


def test_history_builder_wraps_current_message_last() -> None:
    msgs = _history_as_maf_messages(
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        user_message="latest",
    )
    assert [str(m.role).lower() for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1].text == "latest"


def test_history_builder_accepts_none_history() -> None:
    msgs = _history_as_maf_messages(history=None, user_message="only")
    assert len(msgs) == 1
    assert msgs[0].text == "only"


def test_history_builder_skips_other_roles_and_empty_content() -> None:
    """System/tool messages and empty payloads get filtered out."""
    msgs = _history_as_maf_messages(
        history=[
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "kept"},
            {"role": "tool", "content": "ignored"},
        ],
        user_message="final",
    )
    assert [m.text for m in msgs] == ["kept", "final"]


# ─────────────────────── Session rehydration ─────────────


class _FakePool:
    def __init__(self, rows: list[dict] | None = None, raise_on_fetch: Exception | None = None) -> None:
        self._rows = rows or []
        self._raise = raise_on_fetch
        self.last_query: str | None = None
        self.last_args: tuple | None = None

    async def fetch(self, query: str, *args):
        self.last_query = query
        self.last_args = args
        if self._raise is not None:
            raise self._raise
        return self._rows


@pytest.mark.asyncio
async def test_rehydrate_returns_none_when_session_id_missing() -> None:
    assert await _rehydrate_history_from_session("") is None


@pytest.mark.asyncio
async def test_rehydrate_reads_messages_by_conversation_id(monkeypatch) -> None:
    rows = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi back"},
        {"role": "tool", "content": "ignored"},       # non-user/assistant filtered
        {"role": "user", "content": ""},              # empty content filtered
        {"role": "user", "content": "still here"},
    ]
    fake_pool = _FakePool(rows=rows)
    monkeypatch.setattr("shared.db.get_pool", lambda: fake_pool)

    history = await _rehydrate_history_from_session("11111111-1111-1111-1111-111111111111")

    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi back"},
        {"role": "user", "content": "still here"},
    ]
    # uses the $2 LIMIT parameter — no string interpolation.
    assert "LIMIT $2" in (fake_pool.last_query or "")
    assert fake_pool.last_args == ("11111111-1111-1111-1111-111111111111", 50)


@pytest.mark.asyncio
async def test_rehydrate_swallows_db_errors(monkeypatch) -> None:
    fake_pool = _FakePool(raise_on_fetch=RuntimeError("db down"))
    monkeypatch.setattr("shared.db.get_pool", lambda: fake_pool)
    assert await _rehydrate_history_from_session("any-id") is None


@pytest.mark.asyncio
async def test_rehydrate_swallows_missing_pool(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("pool not initialised")

    monkeypatch.setattr("shared.db.get_pool", _boom)
    assert await _rehydrate_history_from_session("any-id") is None


# ─────────────────────── Native path (stubbed agent) ──────


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeStreamingUpdate:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAgent:
    """Tiny stand-in exposing just the ``run`` signatures the helpers use."""

    def __init__(self, text: str = "stubbed-answer") -> None:
        self._text = text
        self.last_call_messages: list | None = None
        self.last_call_stream: bool | None = None
        self.last_options: dict | None = None

    def run(self, messages=None, *, stream: bool = False, options=None, **_kwargs):
        self.last_call_messages = list(messages or [])
        self.last_call_stream = stream
        self.last_options = options

        if stream:
            async def _gen():
                # Two chunks so tests can see incremental yielding.
                for piece in [self._text[: len(self._text) // 2], self._text[len(self._text) // 2 :]]:
                    yield _FakeStreamingUpdate(piece)
            return _gen()

        async def _return():
            return _FakeResponse(self._text)
        return _return()


@pytest.mark.asyncio
async def test_run_agent_native_returns_response_text() -> None:
    agent = _FakeAgent("Paris is the capital of France.")
    text = await _run_agent_native(agent, "What's the capital of France?")
    assert text == "Paris is the capital of France."


@pytest.mark.asyncio
async def test_run_agent_native_pins_temperature() -> None:
    """Every run must carry the configured temperature so identical queries
    produce consistent answers (provider default ~1.0 makes them diverge)."""
    from shared.config import settings

    agent = _FakeAgent("ok")
    await _run_agent_native(agent, "hi")
    assert agent.last_options is not None
    assert agent.last_options.get("temperature") == settings.LLM_TEMPERATURE


@pytest.mark.asyncio
async def test_run_agent_native_threads_history_into_messages() -> None:
    agent = _FakeAgent("ok")
    await _run_agent_native(
        agent,
        "latest",
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    )
    assert agent.last_call_stream is False
    assert agent.last_call_messages is not None
    assert [m.text for m in agent.last_call_messages] == ["hi", "hello", "latest"]


@pytest.mark.asyncio
async def test_run_agent_native_stream_yields_all_chunks() -> None:
    agent = _FakeAgent("Paris is the capital of France.")
    pieces = [chunk async for chunk in _run_agent_native_stream(agent, "hi")]
    assert "".join(pieces) == "Paris is the capital of France."
    assert agent.last_call_stream is True


@pytest.mark.asyncio
async def test_run_agent_native_stream_skips_empty_updates() -> None:
    """Some providers emit empty delta events; the helper must filter them."""

    class _AgentWithEmptyDeltas:
        def run(self, messages=None, *, stream: bool = False, options=None, **_kwargs):
            async def _gen():
                yield _FakeStreamingUpdate("")
                yield _FakeStreamingUpdate("real")
                yield _FakeStreamingUpdate(None)  # type: ignore[arg-type]
            return _gen()

    chunks = [c async for c in _run_agent_native_stream(_AgentWithEmptyDeltas(), "hi")]
    assert chunks == ["real"]


# ─────────────────────── Live LLM parity ───────────────────


def _llm_available() -> bool:
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "azure":
        return bool(
            os.environ.get("AZURE_OPENAI_ENDPOINT")
            and (os.environ.get("AZURE_OPENAI_KEY") or os.environ.get("AZURE_OPENAI_API_KEY"))
        )
    key = os.environ.get("OPENAI_API_KEY", "")
    return bool(key) and not key.startswith("sk-your-")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not _llm_available(), reason="no LLM credentials in .env")
async def test_native_path_against_real_llm() -> None:
    """Proves the native path produces a sensible answer against Azure/OpenAI."""
    from agent_framework import Agent
    from shared.factory import get_chat_client

    agent = Agent(
        get_chat_client(),
        instructions="You are a concise geography assistant. Keep answers to one short sentence.",
        name="native-test-agent",
    )
    answer = await _run_agent_native(agent, "What is the capital of France?")
    assert "paris" in answer.lower(), f"expected Paris in answer, got {answer!r}"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not _llm_available(), reason="no LLM credentials in .env")
async def test_native_path_streams_real_llm_output() -> None:
    from agent_framework import Agent
    from shared.factory import get_chat_client

    agent = Agent(
        get_chat_client(),
        instructions="You are a concise assistant. Keep answers to one short sentence.",
        name="native-stream-agent",
    )
    pieces = [chunk async for chunk in _run_agent_native_stream(agent, "Say 'hi'.")]
    assert pieces, "expected at least one streaming update"
    combined = "".join(pieces).lower()
    assert "hi" in combined
