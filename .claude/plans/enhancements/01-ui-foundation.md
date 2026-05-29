# Phase 1 — UI Foundation + Design System

**Status:** not started · **Depends on:** none · **Unblocks:** all UI phases (2, 3, 5)

## Goal

Build the visual + interaction substrate every later page inherits: a motion system, a grouped
app shell (sidebar + top bar + theme toggle), reusable primitives (stat cards, skeletons, real
charts), and a command palette. WorkGraph-influenced, e-commerce-native, built on the existing
OKLCH/teal tokens.

## Scope

In: motion system, sidebar restructure, top app bar, theme toggle, primitives, recharts wrapper,
Cmd-K palette, token extensions.
Out: page-level content (dashboard, workspaces) — those consume these primitives in later phases.

## Key files

- `web/src/app/globals.css` — extend OKLCH tokens (add elevation/shadow + motion-duration vars);
  do not replace existing palette.
- `web/src/components/sidebar.tsx` — restructure flat nav into grouped sections
  (`Shop` / `Agents` / `Account` / `Admin`), collapse/expand, active-state polish.
- `web/src/app/(app)/layout.tsx` — add top app bar (breadcrumb + global search trigger + theme
  toggle + avatar menu); wire page-transition wrapper.
- `web/src/components/ui/` — new: `stat-card.tsx`, `section-header.tsx`, `skeleton.tsx`,
  `chart.tsx` (recharts wrapper), `theme-toggle.tsx`, `command-palette.tsx`.
- `web/src/components/empty-state.tsx` — extend existing (don't duplicate).
- `web/src/lib/motion.ts` — new: shared framer-motion variants.
- `web/package.json` — add `recharts`; `framer-motion` already present (via `ai-prompt-box.tsx`).

## Steps

1. **Tokens & motion** — add shadow/elevation + duration/easing CSS vars in `globals.css`;
   create `lib/motion.ts` with variants: `pageEnter`, `listStagger`, `cardHover`, `streamPulse`.
   All gated on `prefers-reduced-motion` (use framer-motion `useReducedMotion`).
2. **Theme toggle** — `theme-toggle.tsx` toggling `.dark` on `<html>`, persisted to localStorage,
   SSR-safe (dark tokens already exist; only the toggle is missing).
3. **Sidebar restructure** — grouped sections with labels, icons, role-gated items (reuse role
   logic from `auth-context.tsx`), cart count badge retained, active highlight via primary token.
4. **Top app bar** — breadcrumb from route, global-search button that opens the palette, theme
   toggle, avatar dropdown (profile/logout).
5. **Primitives** — `StatCard` (icon, label, value, delta, trend sparkline slot), `SectionHeader`,
   `Skeleton` set (text/card/table), `Chart` wrapper over recharts themed to chart-1..5 tokens.
6. **Command palette** — Cmd/Ctrl-K, fuzzy nav to routes + quick prompts (seeds Phase 5/2 quick
   actions); built on shadcn dialog + list.

## Tests

- Component render + a11y (roles/labels) for `StatCard`, `SectionHeader`, `Skeleton`, `Chart`,
  `ThemeToggle`, `CommandPalette`.
- `lib/motion.ts` reduced-motion branch unit test.
- Playwright smoke: shell (sidebar groups + top bar) renders for customer/seller/admin roles;
  theme toggle flips `.dark`; Cmd-K opens palette.

## Done when

- New shell renders for all roles with grouped nav + top bar + working theme toggle.
- Primitives exported and used by at least one existing page (e.g. `admin/usage` chart row →
  `Chart`) to prove integration.
- `pnpm lint && pnpm build` clean; component + Playwright smoke green; `verify` skill passes.
