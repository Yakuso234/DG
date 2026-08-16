# AGENTS.md

Guidance for AI coding agents (Codex, etc.) working in this repository.

## DG transition notice

This repository is being refactored from the upstream e-commerce demo into
**DG / FlowPilot**, an enterprise ticket-resolution multi-agent platform.
Existing e-commerce code is a reference baseline, not the target product.

Read files in this order before changing code:

1. `PROJECT_MEMORY.md` (local-only, Chinese, current project truth)
2. `docs/DG-项目目标与路线图.md`
3. this file
4. `CLAUDE.md` and `CONTRIBUTING.md` for upstream architecture and commands

When the upstream guides conflict with `PROJECT_MEMORY.md` or the DG roadmap,
the DG documents win. In particular, the upstream requirement to place all
working memory under `.claude/` does not override the user's explicit request
for a root-level, local-only `PROJECT_MEMORY.md`.

Do not treat existing product, order, pricing, review, inventory, or shopping
UI functionality as completed FlowPilot work. Do not push to `upstream`.

Keep these local-only files out of Git:

- `PROJECT_MEMORY.md`
- `docs/DG-问题与面试复盘.md`

Before a pause or context compaction, update `PROJECT_MEMORY.md` in Chinese.
Only record interview-worthy engineering problems in the local review file.

For current contributor setup and the upstream definition of done, see
`CONTRIBUTING.md`. Frontend-specific upstream notes remain in
`docs/frontend.md` until the FlowPilot frontend is rebuilt.
