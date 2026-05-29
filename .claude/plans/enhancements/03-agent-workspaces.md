# Phase 3 — Per-Agent Workspace Pages

**Status:** not started · **Depends on:** Phase 1 (primitives), benefits from Phase 4 (stats)

## Goal

Give each specialist agent a dedicated workspace page (the QA-Buddy pattern from the WorkGraph
reference): capability hero, example-prompt chips, a live stats strip, recent runs, and an
optional two-pane "config → results" workspace for action-oriented agents.

## Scope

In: dynamic route `(app)/agents/[slug]`, agent metadata source, stats strip, recent runs, prompt
chips, optional two-pane for 1–2 agents, marketplace "Open" wiring.
Out: building brand-new agent capabilities (that's Phase 7); this surfaces existing agents.

## Agents (slugs)

`product-discovery`, `order-management`, `pricing`, `reviews`, `inventory`, `support`
(plus the orchestrator as a meta entry on the index). Map slugs ↔ the agent registry the
orchestrator already uses (`AGENT_REGISTRY` / agent-card metadata).

## Key files

- `web/src/app/(app)/agents/page.tsx` — index grid (reuse marketplace card styling).
- `web/src/app/(app)/agents/[slug]/page.tsx` — new workspace.
- `web/src/components/agents/` — new: `agent-hero.tsx`, `capability-badges.tsx`,
  `example-prompts.tsx`, `agent-stats-strip.tsx`, `recent-runs.tsx`, `two-pane-workspace.tsx`.
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
4. **Two-pane** — for action agents (e.g. pricing: left = product/coupon scope form, right =
   results); drive through existing chat/A2A path, reusing rich cards.
5. **Marketplace wiring** — "Open" → workspace; keep request/approval flow intact.

## Tests

- Route-by-role access tests (gated agents respect approval state from marketplace).
- Stat aggregation query tests (testcontainers) for the usage rollups.
- Playwright: open each agent workspace; example-prompt chip deep-links into chat.

## Done when

- All six agents have a workspace reachable from index + marketplace.
- Stats strip reflects real `usage_logs` once Phase 4 populates them (zeros before, no crash).
- `pnpm lint && pnpm build` clean; tests + Playwright green; `verify` passes.
