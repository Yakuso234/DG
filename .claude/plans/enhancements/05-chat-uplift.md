# Phase 5 — Chat Uplift

**Status:** not started · **Depends on:** Phase 1, integrates Phase 4 step events

## Goal

Polish the showpiece. Bring the prompt box and streaming experience to the WorkGraph reference
level (image 3), and tie per-agent "thinking" states to the Phase 4 step stream.

## Scope

In: prompt-box modes + suggestions, streaming caret/indicators, per-agent thinking states,
message actions, card transition polish.
Out: the timeline panel itself (Phase 4); rich-card data model changes.

## Key files

- `web/src/components/ui/ai-prompt-box.tsx` — mode chips (Auto / pick-an-agent), suggested-prompt
  starters, keep mic, "Enter to send · Shift+Enter newline" hint, smoother send/stop transitions.
- `web/src/app/(app)/chat/page.tsx` — wire mode selection into the request; per-agent thinking
  indicator driven by `onStep` (Phase 4); message action bar.
- `web/src/components/chat/rich-message.tsx` — refine card mount/stream transitions (Phase 1
  motion variants); keep existing parsing + `rehype-sanitize`.
- `web/src/components/chat/` — new `message-actions.tsx` (copy, retry, share/permalink).

## Steps

1. **Prompt box** — mode chips; when an agent mode is chosen, scope the request to that agent
   (deep-linkable from Phase 3 chips / Phase 2 quick prompts). Suggested-prompt row when input is
   empty. Keyboard hint. Preserve existing image-attach + voice features.
2. **Streaming UX** — replace the three-dot bounce with a per-agent thinking state ("Routing… →
   Product Discovery is searching…") sourced from Phase 4 `step` events; smooth streaming caret.
3. **Message actions** — copy, retry (re-run prompt), share/permalink to a conversation.
4. **Card transitions** — product/order/checkout cards mount with the shared motion variants.

## Tests

- Keep + extend `rich-message` parsing tests (product/order/checkout/text detection).
- Prompt-box unit tests: mode selection, suggestions, keyboard send/newline.
- Playwright: full streaming flow with a mode selected; thinking states appear; copy/retry work.

## Done when

- Prompt box matches the reference (modes, suggestions, hints) with attach + voice intact.
- Thinking states reflect real routing from Phase 4; message actions work.
- `pnpm lint && pnpm build` clean; tests + Playwright green; `verify` passes.
