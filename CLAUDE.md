# DG / FlowPilot contributor guide

This repository has been refactored from an upstream e-commerce demo into
**DG / FlowPilot**, a Python enterprise ticket-resolution Agent platform.
The supported product path is `agents/python/flowpilot`; deleted e-commerce
specialists and MCP packages remain recoverable from Git history, not as a
runtime dependency.

Read `PROJECT_MEMORY.md` and `docs/DG-项目目标与路线图.md` before changing the
FlowPilot path. Local memory and interview-review documents are not committed.

## Key commands

```bash
# Python checks
cd agents/python
uv run ruff check flowpilot tests/flowpilot
uv run ruff format --check flowpilot tests/flowpilot
uv run pytest

# Deterministic evaluation
uv run python -m flowpilot.evaluation \
  --dataset evals/datasets/flowpilot_video_ops.json --repeat 3 --summary-only

# Real structured-model evaluation (requires local environment configuration)
FLOWPILOT_STRUCTURED_MODEL=qwen \
uv run python -m flowpilot.evaluation \
  --dataset evals/datasets/flowpilot_video_ops.json \
  --structured-model-from-env --repeat 3 --summary-only

# Local FlowPilot API and workbench
uv run uvicorn flowpilot.api.main:app --host 127.0.0.1 --port 8090
cd ../../web && pnpm dev
```

## Boundaries

- The LangGraph graph may request structured suggestions, but domain code owns
  action allowlists, parameter scope, risk, approval and idempotency.
- `FLOWPILOT_AUTH_MODE=headers` is local Demo-only. `jwt-local` is verified
  locally; RS256/JWKS is not implemented or claimed as complete.
- DG and SW remain separate projects. Their optional integration uses explicit
  HTTP/MCP contracts and never direct cross-project database access.
