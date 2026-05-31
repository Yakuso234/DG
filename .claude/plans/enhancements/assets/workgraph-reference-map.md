# WorkGraph reference → e-commerce-agents mapping

Source of influence: workgraph.ai (https://github.com/nitin27may/workgraph.ai). Take patterns,
not pixels — adapt to the shopping/concierge domain. Professional palette, no purple/AI clichés.

| WorkGraph screenshot | Pattern to borrow | Where it lands here |
|---|---|---|
| **Image 1 — "My Day" dashboard** | Greeting header, card grid (schedule/comms/tasks/activity), grouped sidebar (Workspace/Agents/Discover), light/dark toggle, avatar block | Phase 2 authenticated concierge home; Phase 1 grouped sidebar + theme toggle |
| **Image 2 — QA Buddy agent page** | Per-agent hero + CTA, KPI stat cards, "active plans" cards with progress bars, recent-items table | Phase 3 agent workspace; Phase 1 `StatCard` + `Chart` |
| **Image 3 — prompt box** | Clean composer, mode chips (Auto/Research), mic, "Enter to send · Shift+Enter for newline" hint | Phase 5 `ai-prompt-box.tsx` (modes = pick-an-agent) |
| **Image 4 — two-pane workspace** | Left config panel (KB/stories/approach) → right results pane, "No results yet" empty state | Phase 3 `two-pane-workspace.tsx` for action agents (e.g. pricing) |

## Domain translation

- "Agents" group → the 6 e-commerce specialists (product discovery, orders, pricing, reviews,
  inventory, support).
- "My Day" → "Your storefront / concierge": recent orders, cart snapshot, recommendations, agent
  activity.
- "QA Buddy generate test cases" → action-agent two-pane (e.g. pricing scope → quote results).
- Keep the existing OKLCH/teal token system; do not adopt WorkGraph's exact colors.

## Animation cues

Smooth page transitions, card hover-lift, list stagger, streaming pulse — all via Phase 1
`lib/motion.ts`, gated on `prefers-reduced-motion`.
