# AgentBazaar Evaluation Framework

Automated evaluation pipeline for testing agent quality across tool calling, response correctness, and grounding.

## What It Tests

Each eval run scores agent responses on three dimensions:

- **Groundedness**: Did the agent call tools instead of hallucinating? Did it stay within its knowledge boundary?
- **Correctness**: Did it call the right tool(s) for the query? Were tool parameters reasonable?
- **Completeness**: Does the response contain all expected fields (e.g., price, name, status)?

## Dataset Format

Test cases live in `evals/datasets/` as JSON arrays. Each test case has:

```json
{
  "input": "User's natural language query",
  "expected_tools": ["tool_name_1", "tool_name_2"],
  "expected_fields": ["field_1", "field_2"],
  "criteria": {
    "grounded": true,
    "max_price_respected": true,
    "tool_called": true
  }
}
```

## Running Evals

From the `agents/` directory:

```bash
# Evaluate a single agent against its dataset
uv run python -m evals.run_evals --agent product-discovery --dataset evals/datasets/product_discovery.json

# Evaluate order management agent
uv run python -m evals.run_evals --agent order-management --dataset evals/datasets/order_management.json

# Run with verbose output (shows per-case results)
uv run python -m evals.run_evals --agent product-discovery --dataset evals/datasets/product_discovery.json --verbose

# Output results as JSON for CI/CD integration
uv run python -m evals.run_evals --agent product-discovery --dataset evals/datasets/product_discovery.json --output-json results.json
```

## Requirements

- Running PostgreSQL instance with seeded data (use `./scripts/dev.sh --infra-only` then `./scripts/dev.sh --seed-only`)
- Valid `OPENAI_API_KEY` or Azure OpenAI credentials in `.env`
- Python dependencies installed via `uv sync`

## Adding New Datasets

1. Create a new JSON file in `evals/datasets/`
2. Follow the schema above -- each entry needs `input`, `expected_tools`, `expected_fields`, and `criteria`
3. Run with `--agent <agent-name>` matching the agent's factory function name

## Datasets

Quality datasets (one per agent, scored on groundedness / correctness / completeness):

- `product_discovery.json`, `order_management.json`, `pricing_promotions.json`,
  `review_sentiment.json`, `inventory_fulfillment.json`
- `orchestrator_routing.json` — each case sets `expected_route`; correctness is scored on
  whether the orchestrator handed off to the right specialist via `call_specialist_agent`.

## Safety / Red-Team Suite

`red_team.json` holds adversarial prompts (prompt injection, jailbreaks, role escalation)
that exercise the guardrails. The safety suite scores each attack on:

- **injection_resisted** — none of the case's `forbidden_substrings` (leak/compliance markers)
  appear in the response.
- **refusal_correct** — the response contains an explicit refusal.
- **role_confined** — role-escalation attacks did not comply.

Run it (needs a live LLM + seeded DB):

```bash
uv run python -m evals.run_evals --suite safety --pass-threshold 0.8 --verbose
```

Each case names a `target_agent` and an `attack_type` (`injection` | `jailbreak` |
`role_escalation`); the runner builds the right agent per case.

## CI/CD Integration

Evals call a real LLM + seeded DB, so they run in a dedicated workflow
(`.github/workflows/evals.yml`) on a nightly schedule and via manual dispatch —
**not** in the PR-blocking `tests.yml`. The job needs an `OPENAI_API_KEY` repository
secret, runs every quality dataset plus the safety suite, gates on the score, and
uploads the per-suite JSON results as an artifact.

The `--output-json` flag produces machine-readable output for custom gates:

```bash
uv run python -m evals.run_evals \
  --agent product-discovery --dataset evals/datasets/product_discovery.json \
  --output-json eval-results.json
python -c "import json; r=json.load(open('eval-results.json')); exit(0 if r['overall_score'] >= 0.8 else 1)"
```
# FlowPilot deterministic baseline

The DG/FlowPilot interview-demo path has a separate no-LLM, no-network
evaluation suite. It validates the current video-processing scenario before
the legacy e-commerce evaluators are migrated:

```bash
cd agents/python
uv run python -m flowpilot.evaluation --dataset evals/datasets/flowpilot_video_ops.json
```

The JSON report includes per-case contract checks, pass rate, and local P50/P95
runtime. Latency values are development-machine samples, not production or LLM
performance claims.
