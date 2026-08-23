# FlowPilot evaluation suite

`flowpilot_video_ops.json` is the supported evaluation dataset for the
DG/FlowPilot interview-demo path. It has 30 controlled short-video processing
cases: 12 valid leased `PROCESSING` recoveries and 18 fail-closed rejections.

Proposal cases assert the exact allowlisted action, immutable scoped parameters,
Evidence source/reference, authoritative risk and TraceId. Rejection cases also
assert the exact reason: `non_processing_status` or `missing_lease_evidence`.
The dataset includes untrusted error-summary inputs such as instruction override,
HTML/system tags, forged JSON tool calls, role escalation and delimiter escape.

```bash
cd agents/python

# no LLM/network: deterministic contract baseline
uv run python -m flowpilot.evaluation \
  --dataset evals/datasets/flowpilot_video_ops.json --repeat 3 --summary-only

# configured real structured model: 42 calls per run, 126 for repeat=3
FLOWPILOT_STRUCTURED_MODEL=qwen \
uv run python -m flowpilot.evaluation \
  --dataset evals/datasets/flowpilot_video_ops.json \
  --structured-model-from-env --repeat 3 --summary-only
```

The report separates provider model latency from end-to-end graph latency and
records input/output/total tokens when the provider supplies usage. A passing
fixed dataset is system-evaluation evidence, not an open-domain accuracy,
complete rationale-groundedness or production-SLA claim.
