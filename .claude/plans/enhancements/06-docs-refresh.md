# Phase 6 — Docs Refresh

**Status:** not started · **Depends on:** Phases 1–5 (so screenshots/docs reflect final UI)

## Goal

Close the documentation gaps and add a visual/video tour so the repo reads as a polished,
recruiter-ready showcase. Run the `docs-sync` skill first to get a drift patch list against the
final code, then apply.

## Scope

In: new frontend doc, troubleshooting, CONTRIBUTING, AGENTS/CLAUDE dedup, real `web/README.md`,
screenshot gallery + demo video doc, README status/roadmap update, telemetry Langfuse note.
Out: rewriting the tutorial chapters (separate content track).

## Key files / deliverables

- `docs/frontend.md` — **new**: routes, route groups, design system/tokens, component inventory
  (chat cards, sidebar, primitives), SSE streaming + `event: step` timeline, theme system.
- `docs/troubleshooting.md` — **new**: Docker won't start, Postgres/pgvector connection,
  `dev.sh` flags, embeddings generation, port conflicts, OpenAI/Azure config issues.
- `CONTRIBUTING.md` — **new**: setup, the test/coverage policy (80/70, testcontainers, never mock
  LLM), lint, PR checklist — lifted out of AGENTS.md so it isn't the only source.
- `AGENTS.md` / `CLAUDE.md` (root) — **dedup** the identical 177-line twins: make one canonical,
  have the other reference it (the `web/` dir already uses the `@AGENTS.md` include pattern).
- `web/README.md` — replace Next.js boilerplate with real frontend overview + link to
  `docs/frontend.md`.
- `docs/demo.md` — **new**: embedded demo video + guided scenario walkthrough.
- `README.md` — screenshot gallery (from Playwright captures), accurate shipped-vs-planned status,
  link the new docs, point to `.claude/plans/enhancements/` for the roadmap.
- `docs/telemetry.md` — add the optional Langfuse parallel-sink section (flag-gated, future).

## Steps

1. Run `docs-sync` → triage the patch list.
2. Capture the new UI via the existing Playwright screenshot setup (`web/e2e/screenshots/`);
   curate a gallery.
3. Write the new docs; dedup AGENTS/CLAUDE; replace `web/README.md`.
4. Update README status/roadmap + embed gallery; add `docs/demo.md` with the video.
5. Cross-link everything; verify no dead links (the old `plans/...` references in
   `agent_host.py` docstring + `deployment.md` point at a removed folder — fix or repoint to
   `.claude/plans/`).

## Tests / checks

- Markdown link check (no dead internal links).
- Screenshots regenerate cleanly from Playwright.
- `docs-sync` reports no remaining critical drift.

## Done when

- All new docs exist and are linked from README; AGENTS/CLAUDE no longer duplicated.
- README shows an accurate status + screenshot gallery + demo video.
- Dead `plans/...` references resolved.
