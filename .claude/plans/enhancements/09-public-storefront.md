# Phase 2.6 — Public E-Commerce Storefront

**Status:** in progress · **Top priority** (front-door rework)

## Why

Real e-commerce starts **public**: browse, search, and use the AI assistant to discover/filter
products with no account. Sign-in is required only for account actions (cart checkout, orders,
tracking, returns, labels, history). Today everything is behind the `(app)` auth gate. Make the
storefront the public front door and gate only account features.

Feasibility: product-discovery tools are already user-agnostic
(`agents/python/product_discovery/tools.py`); only the auth middleware blocks anonymous access.

## Decisions (locked — IA revised)

- **Project landing stays at `/`** (OSS showcase front door); **"Try the demo" → `/shop`**.
- Storefront lives under the `(shop)` group: `/shop`, `/shop/products`, `/shop/cart`, `/shop/assistant`.
- Guest cart (localStorage); sign-in at checkout; migrate guest cart → account on login.
- Normal login (seeded creds); no one-click demo.
- Public discovery assistant `/shop/assistant` + full account chat `/chat` (reuse chat components).

## IA

Landing `/` (public): current architecture/agents/stack page; CTA "Try the demo" → `/shop`;
header Sign in (or account link if authed) + GitHub + theme.

Storefront `(shop)` layout (header: logo→/shop, search, cart, theme, Sign in/avatar; footer →
"About this project" `/` + GitHub):
- `/shop` home (hero, featured/trending via `get_trending_products`, category tiles, search,
  "Ask the assistant").
- `/shop/products`, `/shop/products/[id]` (un-gated).
- `/shop/cart` guest cart; Checkout → login.
- `/shop/assistant` public stateless discovery chat.
- `/login`, `/signup`.

Auth console (`(app)` sidebar shell): `/home`, `/checkout`, `/orders`, `/orders/[id]`, `/profile`,
`/chat` (full), `/admin/*`, `/seller/*`. Cross-link via storefront avatar menu + sidebar
"Storefront → /shop" / "About → /".

## Backend

- `optional_auth` dependency (user if token valid, else anonymous) in `shared/auth.py` /
  orchestrator deps; apply to `/api/products`, `/api/products/{id}`, `/api/chat`, `/api/chat/stream`.
- Middleware: don't 401 those paths when token is missing; everything else stays gated.
- `/api/chat/stream` (`orchestrator/routes.py`): anonymous → skip conversation persistence
  (FK user_id), discovery only; orchestrator prompt nudges sign-in for account actions.
- Tests: pytest + testcontainers (real LLM) — anonymous products + chat work; authed unchanged.

## Frontend

- `(shop)/layout.tsx` public layout; storefront home; move landing to `/about`.
- Un-gate `products/*` (drop `if(!user) return null`); conditional account bits.
- `lib/api.ts`: no `/login` bounce on 401 for public endpoints; token-less calls OK.
- `lib/guest-cart.ts` + `GuestCartProvider` (localStorage); migrate via `api.addToCart` on login.
- Public assistant: stateless reuse of `components/chat/*` + `chatStream`; account cards → sign-in
  prompt when anonymous.
- Design pass: hero, featured rails, category tiles, refined product cards, motion (`lib/motion.ts`),
  responsive — the visible quality bar.

## Verification

- `pnpm lint && pnpm exec tsc --noEmit && pnpm test && pnpm build`; extend `e2e/ui-smoke.spec.ts`
  (anonymous storefront/search/assistant; Checkout→/login; post-login console + cart migration).
- Full stack `./scripts/dev.sh`; incognito browse/search/ask without login, then sign in + checkout
  + orders. Rebuild frontend container to reflect changes.

## Done when

- Logged-out visitors browse, search, and use the assistant to find/filter products at `/`.
- Account actions cleanly prompt sign-in; guest cart migrates; authed console intact.
- All checks + Playwright green; verified end-to-end on the live stack.
