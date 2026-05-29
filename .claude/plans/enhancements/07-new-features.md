# Phase 7 — New Features Backlog

**Status:** backlog · each item sequenced after the phase that unblocks it.

These add demo surface area beyond the core UI/observability work. Each gets its own scope + tests
when picked up. Anything needing new DB tables updates `docker/postgres/init.sql` and the
deterministic seeder (`scripts/seed.py`, `random.seed(42)`), plus `docs/database-schema.md`.

## Backlog

### 1. Guided demo / scenario launcher
Recruiters self-serve the 8 demo scenarios from the README as one-click prompts.
- Unblocked by: Phase 2 (landing/home quick-prompts).
- Surfaces: public landing CTA + authenticated home + Cmd-K palette.
- Build: a `scenarios.ts` registry (title, prompt, expected agents) → chips that deep-link into
  chat prefilled. No backend change.

### 2. Agent runs / traces explorer
Proves real observability depth (recruiter "wow").
- Unblocked by: Phase 4 (schema population).
- Largely delivered by Phase 4's `/runs` page; this item = filters, search, trace_id→Aspire link,
  per-agent drill-down, export.

### 3. Recommendations surfacing
Visible "AI value" on home + product pages.
- Unblocked by: Phase 2.
- Reuse the product discovery agent + existing pgvector embeddings (1536-dim, ivfflat cosine).
  Add a `recommend` path (tool or endpoint) returning ranked products; render a "recommended for
  you" strip. Tests: ranking determinism on seeded data.

### 4. Seller analytics with real charts
Turns the table-only seller dashboard into a story.
- Unblocked by: Phase 1 (recharts `Chart`).
- Wire existing seller stats endpoints into charts (sales over time, top products, returns).

### 5. Wishlist + product comparison
Rounds out the e-commerce flow.
- New tables (`wishlists`, `wishlist_items`) + endpoints + UI; comparison view diffs 2–4 products.
- Seeder + `database-schema.md` updates. Tests: CRUD + per-user isolation (`user_id` filter).

### 6. Notifications / toasts
Order status, request-approved, agent-done feedback.
- Cross-cutting UX primitive (shadcn toast); optional SSE/poll for async events.

### 7. Command palette quick-actions
Power-user/demo polish — actions (not just nav): start scenario, switch agent, jump to order.
- Unblocked by: Phase 1 palette.

### 8. Langfuse integration (optional)
Deep LLM eval/trace dashboards for advanced demos.
- Parallel OTel sink behind `LANGFUSE_ENABLED`; documented in `docs/telemetry.md` (Phase 6).
- Keep OTel/Aspire as primary; Langfuse is additive. Tests: flag-off path unchanged.

### 9. Container image build + publish workflow (+ README badge)
Advertise a build status and (optionally) ship runnable images.
- New `.github/workflows/build-images.yml` building the multi-target Dockerfile (`ARG AGENT_NAME`).
- Two modes: build-smoke only (no push) for a green gate, or build + push to GHCR
  (`ghcr.io/nitin27may/...`) on tag/main (needs `packages: write` + `GITHUB_TOKEN`).
- Add the workflow status badge to `README.md` (Phase 6 badge row).
- Decision needed: publish to GHCR vs build-only. Surface before wiring.

## Prioritization note

Highest showcase ROI: #1 (scenario launcher) + #2 (runs explorer) — both ride on phases already
planned and directly improve a recruiter's first 5 minutes. #5/#8 are larger; schedule last.
