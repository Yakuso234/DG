# Showcase Uplift — Master Plan

> Repo-committed index. Working artifacts live under the repo-local `.claude/` folder (see the
> "Working Artifacts Location" section in the project `CLAUDE.md`).

## Why this exists

This repo is a portfolio/showcase piece: a 6-agent MAF (Microsoft Agent Framework) e-commerce
platform, companion to the MAF v1 tutorial series on nitinksingh.com, and a credibility asset
when applying for freelance/architecture work. The engine is strong; the *presentation* is not
yet at the level the work deserves. Three gaps:

1. **UI is functional but flat** — root just redirects to `/chat`; no dashboard/landing, no
   per-agent workspaces; admin/seller/profile are table-only; "charts" are text rows; minimal
   animation.
2. **The agentic story is invisible** — OTel→Aspire is wired, and the DB already has
   `usage_logs`, `agent_execution_steps`, `messages.metadata`/`agents_involved`, but
   `agent_execution_steps` is never populated, `metadata` is empty, and `agents_involved` is
   never rendered. The multi-agent routing — the whole point — is not visible in a demo.
3. **Docs have gaps** — no frontend doc, no troubleshooting/FAQ, no CONTRIBUTING, boilerplate
   `web/README.md`, duplicated AGENTS.md/CLAUDE.md, no screenshot/video tour.

## Decisions (locked with user)

- Do all four workstreams (UI, agentic log, docs, new features) **in phases**.
- **Built-in timeline first**; Langfuse is documented as an optional future sink, not built now.
- UI takes **influence** from WorkGraph (workgraph.ai) but stays **e-commerce-native**.
- Output as **master + per-item sub-plans** committed in repo-local `.claude/plans/enhancements/`.

## Hard constraints

- Tests are a deliverable at every level — floors 80% unit / 70% integration; testcontainers for
  DB; never mock the LLM. Each phase ships with tests, not after. (`feedback_tests_everywhere`)
- Python: `uv`, ruff, asyncpg, MAF `@tool`, ContextVars for identity, YAML prompts. No custom
  tool registries, no raw OpenAI loops — use **MAF middleware/events** for the timeline.
- Frontend: Next.js 16.x (read `node_modules/next/dist/docs/` before writing), App Router,
  Tailwind 4 + shadcn/ui, existing OKLCH/teal tokens in `web/src/app/globals.css` (extend, don't
  replace).
- Professional palette — no purple/AI-cliché aesthetics; no emojis in docs.

## Phases & sub-plans

Execution order (revised 2026-05-29 after building 1–2 and a Playwright UI audit):

| Order | Phase | Sub-plan | Outcome | Status |
|---|---|---|---|---|
| 1 | 1 | [01-ui-foundation.md](01-ui-foundation.md) | Motion, grouped sidebar shell + top bar + theme toggle, primitives, Cmd-K palette | ✅ done |
| 2 | 2 | [02-dashboard-home.md](02-dashboard-home.md) | Authenticated concierge home + public recruiter landing | ✅ done |
| 3 | 1.5 | [08-dark-mode-migration.md](08-dark-mode-migration.md) | Token-migrate the ~10 pages that still break in dark mode | ⏳ next |
| 4 | 4 | [04-agentic-timeline.md](04-agentic-timeline.md) | Built-in agent timeline (backend capture + SSE + UI) — highest leverage | ⏳ queued |
| 5 | 3 | [03-agent-workspaces.md](03-agent-workspaces.md) | **Lean** per-agent detail pages (after Phase 4 so stats/runs are real) | ⏳ queued |
| 6 | 5 | [05-chat-uplift.md](05-chat-uplift.md) | Prompt-box modes/suggestions, per-agent thinking states, message actions | ⏳ queued |
| 7 | 6 | [06-docs-refresh.md](06-docs-refresh.md) | Frontend doc, troubleshooting, CONTRIBUTING, dedup, screenshot tour, badges | ⏳ queued |
| — | 7 | [07-new-features.md](07-new-features.md) | Feature backlog, each sequenced after its unblocking phase | backlog |

Each phase is independently demo-able. Phase 1 is the substrate; **Phase 4 (agentic timeline) is
the highest-leverage credibility feature and now runs before Phase 3** so the agent pages are
data-rich rather than full of zeros.

**Reorder rationale (2026-05-29):**
- A Playwright dark-mode audit found ~10 pages still using hardcoded `slate`/`white` colors that
  break in dark mode (only home/chat/admin-usage/landing/login/signup are token-clean). The global
  theme toggle makes this user-visible, so the **dark-mode migration (Phase 1.5)** is the next
  fix — see [08-dark-mode-migration.md](08-dark-mode-migration.md).
- **Phase 3 trimmed to a lean agent-detail page** (capabilities + example prompts + real
  stats/runs), dropping the heavy WorkGraph-style two-pane "config → results" — our agents are
  conversational (orchestrator-routed), so a form-driven workspace would be forced. It depends on
  Phase 4's `usage_logs`/`agent_execution_steps` for live data, hence it follows Phase 4.

## Verification (per phase)

- Python: `cd agents/python && uv run ruff check . && uv run ruff format --check . && uv run pytest`
- Frontend: `cd web && pnpm lint && pnpm build`, component/unit tests, `pnpm exec playwright test`
- Full stack: `./scripts/dev.sh`, drive a multi-agent prompt, confirm (a) chat timeline shows
  orchestrator→specialist→tool steps, (b) `usage_logs`+`agent_execution_steps` rows written,
  (c) Aspire (`:18888`) still shows correlated traces via `trace_id`.
- Run the `verify` skill after each phase; never mark a phase done without it.

## Out of scope (for now)

- Replacing OTel/Aspire (kept; Langfuse additive/optional).
- Production/K8s deployment hardening (docs note only).
- Publishing the tutorial chapters (separate content track).
