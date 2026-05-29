# Phase 1.5 — Dark-Mode Token Migration

**Status:** next · **Depends on:** Phase 1 (tokens + theme toggle exist)

## Why

Adding the global theme toggle in Phase 1 made an existing gap user-visible: most pages still use
hardcoded Tailwind `slate`/`white`/`gray` colors instead of the OKLCH theme tokens, so they break
in dark mode (light backgrounds, dark-on-dark / invisible text). A Playwright dark-mode audit
(2026-05-29, mocked auth) confirmed which pages are affected. The token system itself works — the
already-migrated pages (`/home`, `/chat`, `/admin/usage`, landing, login, signup) render correctly
in both themes.

## The fix (mechanical)

Swap hardcoded classes for tokens, matching the migrated pages:

| Hardcoded | Token |
|---|---|
| `bg-white`, `bg-slate-50` (page/card) | `bg-card` / `bg-background` |
| `text-slate-900` / `-800` | `text-foreground` |
| `text-slate-700` / `-600` / `-500` | `text-muted-foreground` |
| `border-slate-200` | `border-border` (or `ring-1 ring-foreground/10`) |
| `bg-red-50 … text-red-700` | `bg-destructive/10 … text-destructive` |
| status/accent chips | keep semantic colors but add `dark:` variants where needed |

## Pages to migrate (worst-first, from the audit)

1. `web/src/app/(app)/profile/page.tsx` — worst; invisible text. (e.g. `text-slate-900` ~L320,
   `text-slate-500` ~L436).
2. `web/src/app/(app)/admin/page.tsx` — KPI values + two data tables unreadable.
3. `web/src/app/(app)/admin/requests/page.tsx` and `web/src/app/(app)/admin/audit/page.tsx` —
   white card surfaces + slate table text (likely shared table/card markup).
4. `web/src/app/(app)/cart/page.tsx` and `web/src/app/(app)/orders/page.tsx` — light wrapper +
   slate item/order text.
5. `web/src/app/(app)/products/page.tsx` (e.g. `text-slate-500` ~L84) and
   `web/src/app/(app)/marketplace/my-agents/page.tsx` — light content bg + low-contrast pills/tables.
6. `web/src/app/(app)/marketplace/page.tsx` (search input) and `web/src/app/(app)/seller/page.tsx`
   (recent-orders table, buttons) — partial.

Also sweep `web/src/components/**` for any chat/order/product card components using hardcoded slate
(e.g. `empty-state.tsx` uses `bg-slate-100`/`text-slate-400`/`text-slate-800`).

## Approach

- Grep for offenders: `rg "slate-|bg-white|text-gray-" web/src/app web/src/components`.
- Migrate page by page; keep light-mode appearance identical (tokens resolve to the same light
  palette).
- After each page, re-validate in dark mode with Playwright (mocked auth) — reuse the audit harness
  / `e2e/ui-smoke.spec.ts` patterns; spawn a subagent to screenshot + eyeball.

## Tests / verification

- Extend `e2e/ui-smoke.spec.ts` (or a dark-mode spec) to load each migrated route in dark and
  assert no light leak — e.g. computed `background-color` of the main container is the dark token,
  not white. (Pragmatic: screenshot + subagent review per page.)
- `pnpm lint && pnpm exec tsc --noEmit && pnpm build` clean.

## Done when

- All app pages render correctly in dark mode (no white backgrounds, no invisible text).
- `rg "slate-|bg-white"` over `web/src/app` + `web/src/components` returns only intentional cases.
- Dark-mode Playwright pass is green across the page set.
