# Phase 4 — Built-in Agentic Timeline (Observability)

**Status:** not started · **Depends on:** Phase 1 (UI primitives) · **Highest leverage**

## Goal

Make the multi-agent work visible to users/recruiters: a live timeline of
orchestrator → specialist → tool calls in chat, plus a persisted runs/traces explorer — using the
DB schema that already exists but is never written to. No new infra; Langfuse stays optional.

## Background (verified)

- `agents/python/shared/usage_db.py` already defines `log_agent_usage`, `log_execution_step`,
  `UsageTimer` — **`log_execution_step` is never called** and `usage_logs`/`agent_execution_steps`
  go mostly/entirely unpopulated.
- `messages.metadata` (JSONB) and `messages.agents_involved` (array) exist; `agents_involved` is
  captured in the SSE `metadata` frame but **never rendered**; `metadata` is left empty.
- Execution now runs through MAF-native `agent.run()` (the old custom tool loop in
  `agent_host.py` was retired) — so capture tool calls via **MAF middleware/events**, not a custom
  loop. Tutorials ch06 (middleware) / ch08 (events) are the showcase tie-in.
- A2A `/message:send` is request/response (returns `{"response": text}`), so specialists can't
  stream to the orchestrator mid-run — they return a compact `steps[]` summary the orchestrator
  forwards as SSE frames; the orchestrator's own routing events stream live.
- `telemetry.py` provides `tool_call_span`, `get_current_trace_id` — reuse for Aspire correlation.
- `/api/admin/audit` in `routes.py` already LEFT JOINs `agent_execution_steps` (shows none today
  because they're never written).

## Backend — capture + stream

1. **Middleware** — add a MAF function-invocation + agent-run middleware attached in every
   `create_*_agent()` (orchestrator + specialists). On each tool call: (a) call
   `log_execution_step(usage_log_id, idx, tool_name, tool_input, tool_output, status, duration)`;
   (b) push a compact step event onto a per-request `asyncio.Queue` held in a ContextVar
   (`shared/context.py` pattern).
2. **Usage row per run** — wrap runs with `UsageTimer` + `log_agent_usage(...)` so each invocation
   yields a `usage_logs` row (with `trace_id`) that the steps FK to. Populate `messages.metadata`
   with `{steps: [...], agents_involved: [...]}` and the `agents_involved` column.
3. **A2A summary** — `agent_host.py::message_send` returns `{"response": ..., "steps": [...]}`;
   specialists include their compact step summary.
4. **SSE step frames** — orchestrator `/api/chat/stream` generator in `routes.py` emits, alongside
   `data:` text and the final `metadata`, new `event: step` frames drained from the queue:
   routing decisions (from `call_specialist_agent` in `orchestrator/agent.py`), tool calls, tool
   results, and forwarded specialist steps. Keep within existing disconnect/timeout/byte guards.

## Frontend — render

5. **Stream parse** — extend `web/src/lib/api.ts::chatStream()` to recognize `event: step`
   (today only `data` + `metadata`) and surface a `onStep` callback.
6. **Timeline panel** — collapsible right-rail/drawer in `(app)/chat/page.tsx`: live chain
   orchestrator → specialist(s) → tools, each row expandable to input/output with status +
   duration; render `agents_involved`. New `web/src/components/chat/agent-timeline.tsx`.
7. **Runs/Traces page** — `(app)/runs/page.tsx` reading the now-populated `/api/admin/audit`
   (or a new user-scoped runs endpoint); list runs → drill into step detail; link `trace_id` to
   Aspire. Feeds Phase 3 stats + Phase 2 activity card.

## Langfuse (documented, not built)

- Add a section to `docs/telemetry.md` describing an optional parallel Langfuse sink behind a flag
  (`LANGFUSE_ENABLED`), captured in `07-new-features.md`. Do not add the dependency now.

## Tests

- Integration (testcontainers, **real LLM** per policy): a multi-agent prompt writes ≥1
  `usage_logs` row + ≥1 `agent_execution_steps` row; `messages.metadata` populated.
- SSE contract test: `event: step` frames are emitted and well-formed; guards still hold.
- UI: timeline renders a routed run; runs page lists it and drills into steps.

## Done when

- A live demo prompt shows the orchestrator→specialist→tool timeline in chat.
- `usage_logs` + `agent_execution_steps` rows exist and appear in `/api/admin/audit` and `/runs`.
- Aspire (`:18888`) still shows correlated traces via `trace_id`.
- `uv run pytest` + frontend tests green; `verify` passes.
