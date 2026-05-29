# Phase 3 — Per-Agent Detail Pages (lean)

**Status:** not started · **Runs AFTER Phase 4** (needs real stats/runs) · **Depends on:** Phase 1
primitives + Phase 4 `usage_logs`/`agent_execution_steps`.

> Scope revised 2026-05-29: trimmed from a full "workspace" to a **lean agent-detail page**. Our
> agents are conversational and orchestrator-routed (users don't drive a specialist directly), so
> the WorkGraph-style two-pane "config → results" workspace would feel forced. Build the detail
> page instead, and only consider a two-pane later for a genuinely form-shaped agent (e.g. pricing)
> as a Phase 7 item if it earns its keep.

## Goal

Give each specialist a recruiter-friendly detail page: capability hero + badges, **example-prompt
chips** (deep-link into chat scoped to that agent), a **live stats strip**, and **recent runs** —
proving "here's what each agent does, and evidence it's used."

## Scope

In: dynamic route `(app)/agents/[slug]`, an index grid, shared agent metadata, stats strip + recent
runs (from Phase 4 data), example-prompt chips, marketplace "Open" wiring.
Out: the heavy two-pane "config → results" workspace (dropped); building new agent capabilities
(Phase 7); this only surfaces existing agents.

## Agents (slugs)

`product-discovery`, `order-management`, `pricing`, `reviews`, `inventory`, `support`
(plus the orchestrator as a meta entry on the index). Map slugs ↔ the agent registry the
orchestrator already uses (`AGENT_REGISTRY` / agent-card metadata).

## Key files

- `web/src/app/(app)/agents/page.tsx` — index grid (reuse marketplace card styling).
- `web/src/app/(app)/agents/[slug]/page.tsx` — new workspace.
- `web/src/components/agents/` — new: `agent-hero.tsx`, `capability-badges.tsx`,
  `example-prompts.tsx`, `agent-stats-strip.tsx`, `recent-runs.tsx`.
  (No `two-pane-workspace.tsx` — dropped per the revised scope.)
- `web/src/lib/agents.ts` — new: static agent metadata (name, role, description, capabilities,
  example prompts, accent token) keyed by slug; single source the index + workspace + marketplace
  share.
- `web/src/app/(app)/marketplace/page.tsx` — wire the catalog "Open" action to `/agents/[slug]`.
- Stats: `usage_logs` aggregation via the audit/usage endpoints in
  `agents/python/orchestrator/routes.py` (populated by Phase 4; show zeros gracefully before).

## Steps

1. **Agent metadata** — `lib/agents.ts` with per-agent display data + example prompts; reconcile
   with backend registry so slugs stay in lockstep.
2. **Index** — grid of agent cards linking into workspaces.
3. **Workspace** — hero (icon, role, capability badges), example-prompt chips (deep-link to chat
   scoped to that agent), stats strip (invocations / tokens / avg latency from `usage_logs`),
   recent-runs list (from runs endpoint).
4. **Marketplace wiring** — "Open" → detail page; keep request/approval flow intact.
   (Two-pane workspace intentionally omitted — see scope note.)

## Tests

- Route-by-role access tests (gated agents respect approval state from marketplace).
- Stat aggregation query tests (testcontainers) for the usage rollups.
- Playwright: open each agent workspace; example-prompt chip deep-links into chat.

## Done when

- All six agents have a workspace reachable from index + marketplace.
- Stats strip reflects real `usage_logs` once Phase 4 populates them (zeros before, no crash).
- `pnpm lint && pnpm build` clean; tests + Playwright green; `verify` passes.
