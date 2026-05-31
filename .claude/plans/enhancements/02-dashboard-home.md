# Phase 2 — Dashboard Home + Public Landing

**Status:** not started · **Depends on:** Phase 1 · **Unblocks:** demo flow, Phase 7 launcher

## Goal

Replace the bare root redirect with two real surfaces: an authenticated e-commerce "concierge"
home (WorkGraph *My Day* energy, shopping-native) and a public marketing/architecture landing
aimed at recruiters/visitors.

## Scope

In: authenticated home page + data wiring, public landing, root redirect change, demo-video slot.
Out: the live agent-activity feed's deep internals (consumes Phase 4; show a graceful placeholder
until Phase 4 lands).

## Key files

- `web/src/app/page.tsx` — currently redirect-only. Split: unauthenticated → render landing;
  authenticated → redirect to `/home`.
- `web/src/app/(app)/home/page.tsx` — new authenticated dashboard.
- `web/src/components/home/` — new: `greeting.tsx`, `quick-prompts.tsx`, `recent-orders-card.tsx`,
  `cart-snapshot-card.tsx`, `recommended-strip.tsx`, `agent-activity-card.tsx`.
- `web/src/components/landing/` — new: hero, architecture section (embed `docs/architecture.png`
  or a mermaid render), tutorial-series links, test-user CTA, video slot.
- `web/src/lib/api.ts` — reuse existing orders/cart/products endpoints; add a lightweight
  recent-activity fetch if not already covered (fold into Phase 4's runs endpoint when available).

## Steps

1. **Root split** — `page.tsx`: auth check → landing vs redirect to `/home`. Keep the existing
   loading spinner during auth resolution.
2. **Concierge home** — greeting (name/time), quick-prompt launcher (chips that deep-link into
   `/chat` with a seeded prompt), recent-orders card (reuse orders API), cart snapshot (reuse
   `cart-context.tsx`), recommended-for-you strip (product discovery / pgvector — placeholder
   ranking acceptable until Phase 7 recommendations), agent-activity card (placeholder → Phase 4).
3. **Public landing** — hero with one-line value prop, 6-agent architecture diagram, "how it
   works" (A2A + orchestrator), tutorial-series link block (link to nitinksingh.com chapters),
   seeded test-user credentials + "Try the demo" CTA, embedded demo-video slot (user supplies).
4. **Responsive + motion** — use Phase 1 motion variants; card grid responsive like WorkGraph.

## Tests

- Data-binding unit tests for each home card against seeded demo data (deterministic seeder,
  `random.seed(42)`).
- Playwright: authenticated root redirects to `/home` and cards render per role; unauthenticated
  root renders landing with working CTA → `/login`.

## Done when

- Authenticated users land on a populated concierge dashboard; visitors see a real landing.
- Quick-prompt chips deep-link into chat with the prompt prefilled.
- `pnpm lint && pnpm build` clean; tests + Playwright green; `verify` passes.
