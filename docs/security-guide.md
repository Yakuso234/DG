# Security Guide

Defense-in-depth security architecture for the E-Commerce Agents multi-agent platform. This guide covers the threat model, guardrails stack, authentication and identity propagation, data access controls, and the hardening roadmap.

See [`docs/agent-audit-matrix.md`](agent-audit-matrix.md) for the per-agent status snapshot.

---

## Threat Model

### Attack surface

```
Browser  ──JWT──►  Orchestrator (:8080)  ──X-Agent-Secret──►  Specialists (:8081–8085)
                         │                                           │
                    PostgreSQL / pgvector                        Redis (cache)
```

The platform has two principal trust boundaries:

1. **Browser → Orchestrator** — unauthenticated HTTP. Attacker is any internet client.
2. **Orchestrator → Specialists** — internal network, shared secret. Attacker is a compromised container that knows the secret but may supply arbitrary headers.

### Threat categories

| Category | Vector | Defenses applied |
|----------|--------|-----------------|
| **Direct prompt injection** | Attacker crafts a user message containing `ignore previous instructions` or a fake turn prefix | `InjectionDetectionChatMiddleware` (observe) + `grounding-rules.yaml` (prompt layer) |
| **Stored / indirect injection** | Adversarial text embedded in product descriptions, review bodies, or order notes that re-enters the model as a tool result | `OutputSanitizationMiddleware` neutralizes before re-injection |
| **Role escalation** | Attacker claims to be admin/seller in the message body | `grounding-rules.yaml` role-confinement rules + `@requires_role` decorator on privileged tools + SQL ownership filters |
| **Identity spoofing (inter-agent)** | Compromised caller forwards arbitrary `x-user-email` / `x-user-role` headers alongside a valid secret | `_identity_anomaly()` validation + `GUARDRAILS_STRICT_IDENTITY` flag |
| **JWT forgery / replay** | Attacker supplies an expired or tampered Bearer token | `decode_token()` with HS256 + `jwt.ExpiredSignatureError` / `jwt.InvalidTokenError` handling |
| **Unauthorized tool access** | Unauthenticated or low-privilege caller invokes destructive tools (cancel order, place backorder) | `@requires_role` + SQL `WHERE user_id = $N` ownership filters |
| **Secret exfiltration** | Injection payload attempts to extract `AGENT_SHARED_SECRET` or `JWT_SECRET` | Prompt-layer refusal rules; sanitization strips control chars used for hidden payloads |
| **SQL injection** | Attacker embeds SQL in search queries or filter values | Parameterized `asyncpg` queries (`$1, $2, …`) throughout; no string-concatenated SQL |
| **Data over-fetch** | Tool returns more rows than intended | `LIMIT` clamping in every list query; ownership filter on every user-facing query |

---

## Guardrails Stack

The guardrails follow a defense-in-depth model: **prompt layer → code layer**, each adding an independent line of defense. All code-layer guardrails are flag-gated via `shared/config.py` so they can be toggled without a redeploy.

### Middleware composition order

Every specialist agent is initialized with `build_specialist_middleware()` from `shared/middleware.py`. The stack (inner to outer, i.e. first to execute) is:

```
Request →
  1. InjectionDetectionChatMiddleware   # scan inbound messages (observe-only by default)
  2. AgentRunLogger                     # correlation ID + start/finish log
  3. ToolAuditMiddleware                # structured log per tool call
  4. OutputSanitizationMiddleware       # neutralize tool results before re-entry
  ← Response
```

`include_steps=True` appends a step-logging middleware for detailed tracing (used in development).

### Layer 1 — Prompt-layer rules (`grounding-rules.yaml`)

`shared/config/prompts/_shared/grounding-rules.yaml` is injected into every agent's system prompt via the YAML composition system (`shared/prompt_loader.py`). It enforces three invariants at the model level:

- **Data grounding** — every answer must originate from a tool call; the model must not fabricate data from training.
- **Prompt-injection resistance** — tool results and user text are data, never instructions. Fake system/developer turns are explicitly forbidden.
- **Role confinement** — the model's privileges are fixed by the system-supplied role; in-message claims of escalated privilege must be ignored.

This layer is the broadest defense. Its weakness is that it is only as reliable as the model's instruction-following.

### Layer 2 — Inbound injection detection (`InjectionDetectionChatMiddleware`)

`shared/guardrails/injection_middleware.py` scans each inbound chat message against nine high-precision regex patterns in `shared/guardrails/sanitize.py`. Patterns cover:

- `ignore/disregard previous instructions`
- `forget all rules`
- `you are now a/an/the …`
- Fake turn prefixes (`system:`, `developer:`, `assistant:` at line start)
- Prompt reveal attempts (`reveal your system prompt`)
- XML-style injection tags (`</system>`, `<instructions>`)
- Privilege escalation phrasing (`act as if you are an admin`)

**Default behavior**: observe-only. Detections increment a counter, set `context.metadata["guardrail_injection_detected"]`, and log at INFO. Set `GUARDRAILS_BLOCK_ON_INJECTION=true` to log at WARNING; blocking of the request itself requires a custom middleware that reads the metadata flag.

**False-positive rate**: patterns are deliberately high-precision to avoid blocking legitimate phrasing. The safety/red-team eval suite (`evals/safety_evaluator.py`) continuously measures both precision and recall.

### Layer 3 — Stored-injection neutralization (`OutputSanitizationMiddleware`)

`shared/guardrails/output_middleware.py` runs after each tool invocation. If the tool name appears in `SANITIZE_TOOLS` (`shared/guardrails/config.py`), `neutralize_value()` rewrites the result in place before it is returned to the model.

`neutralize_value()` (`shared/guardrails/sanitize.py`) does two things:

1. **Strip** — removes C0 control characters (except TAB/LF/CR), DEL, zero-width Unicode marks, line/paragraph separators, and BOM. These are common hidden-payload carriers.
2. **Defang** — replaces pattern matches with `[neutralized]`, preserving the structure and length so downstream analysis (fake-review detection, sentiment) can still see that something was there.

Only the tools whose results carry user-generated free text are in `SANITIZE_TOOLS`. Each entry optionally specifies a field allowlist so structured fields (prices, SKUs) are never mangled.

**Fail behavior**: controlled by `GUARDRAILS_FAIL_OPEN` (default `true`). On an unexpected exception, the raw result is returned and the error is logged. Set `GUARDRAILS_FAIL_OPEN=false` for fail-closed behavior in high-security deployments.

### Layer 4 — Tool-level role authorization (`@requires_role`)

`shared/guardrails/roles.py` provides two forms:

```python
# Decorator — place directly under @tool so MAF introspects the original signature
@tool(name="get_my_products", description="…")
@requires_role("seller", "admin")
async def get_my_products(…): …

# Guard clause — for retrofitting existing tools without re-ordering decorators
denied = ensure_role("seller", "admin", tool="get_my_products")
if denied:
    return denied
```

`admin` is always allowed (superuser) regardless of the `roles` argument. Identity is read from the `current_user_role` ContextVar, which is set by `AgentAuthMiddleware` and never passed as a function argument.

All four tools in `shared/tools/seller_tools.py` (`get_seller_products`, `update_product_price`, `get_seller_analytics`, `get_payout_summary`) carry `@requires_role("seller", "admin")`. See the [audit matrix](agent-audit-matrix.md) for the remaining open items.

### Configuration flags

| Flag | Default | Effect |
|------|---------|--------|
| `GUARDRAILS_ENABLED` | `true` | Master switch. `false` disables all code-layer guardrails. |
| `GUARDRAILS_OUTPUT_SANITIZATION` | `true` | Enable/disable `OutputSanitizationMiddleware`. |
| `GUARDRAILS_BLOCK_ON_INJECTION` | `false` | Log injection detections at WARNING instead of INFO. |
| `GUARDRAILS_FAIL_OPEN` | `true` | Sanitization errors return the raw result rather than raising. |
| `GUARDRAILS_STRICT_IDENTITY` | `false` | Reject inter-agent calls with malformed forwarded identity. |
| `GUARDRAILS_INJECTION_PROVIDER` | `regex` | Reserved for future Azure AI Content Safety integration. |

---

## Authentication and Identity Flow

### External requests (Browser → Orchestrator)

```
Authorization: Bearer <JWT>
```

`AgentAuthMiddleware` (`shared/auth.py`) validates the token using `decode_token()` (`shared/jwt_utils.py`):

1. HS256 decode with `JWT_SECRET`
2. Checks `type == "access"` claim (refresh tokens are rejected)
3. Extracts `sub` (email), `role`, and `user_id` from the payload
4. Sets three ContextVars: `current_user_email`, `current_user_role`, `current_session_id`

Paths `/health` and `/.well-known/agent-card.json` bypass auth.

JWT signing uses `bcrypt` for passwords and `PyJWT` for token generation. Default `JWT_SECRET` is `change-me-in-production` — the config validator warns if this is not overridden at startup.

### Inter-agent requests (Orchestrator → Specialists)

```
X-Agent-Secret: <AGENT_SHARED_SECRET>
X-User-Email:   alice@example.com
X-User-Role:    customer
X-Session-ID:   <session>
```

The shared secret authenticates the caller (proves it is a platform agent, not an external client). The forwarded `X-User-Email` and `X-User-Role` headers carry the end-user's identity through the agent chain.

`_identity_anomaly()` validates the forwarded headers:

- `role` must be one of `customer`, `seller`, `admin`, `system`
- `email` must contain `@` (unless it is the sentinel value `system`)

If `GUARDRAILS_STRICT_IDENTITY=true`, anomalies result in a 401 instead of a logged warning.

### Identity propagation via ContextVars

`shared/context.py` exposes three `contextvars.ContextVar` objects: `current_user_email`, `current_user_role`, `current_session_id`. Auth middleware sets these at the request boundary; every tool reads from them directly. Identity is never threaded through function arguments.

This means the identity chain is:

```
HTTP request → AgentAuthMiddleware.dispatch()
             → ContextVar.set(email, role, session_id)
             → tool function
             → current_user_role.get()
             → @requires_role check / SQL WHERE clause
```

---

## Data Access Controls

### SQL ownership filters

Every user-facing query uses a parameterized `WHERE user_id = $N` or `WHERE u.email = $N` clause. No query returns rows belonging to other users. This is enforced at the query level — not in the tool's Python logic — so it cannot be bypassed by prompt injection.

Example (all queries follow this pattern):

```sql
SELECT * FROM orders
WHERE user_id = (SELECT id FROM users WHERE email = $1)
ORDER BY created_at DESC
LIMIT 20
```

### LIMIT clamping

All list queries include an explicit `LIMIT`. Tools that accept a user-supplied `limit` argument clamp it to a maximum:

```python
async def get_user_orders(limit: Annotated[int, "Max results"] = 10) -> list[dict]:
    effective_limit = min(limit, 50)  # caller cannot exceed 50
    …
```

### Parameterized queries

All database access uses `asyncpg`'s parameterized query syntax (`$1, $2, …`). No string concatenation is used to build SQL. This eliminates SQL injection at the query-construction layer.

---

## Azure AI Content Safety — Optional Integration

The `GUARDRAILS_INJECTION_PROVIDER` config flag reserves the integration point for [Azure AI Content Safety Prompt Shields](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection). When set to `azure-content-safety`, the injection detection pipeline would call the Prompt Shields API before the regex layer, providing a cloud-backed ML classifier with higher recall and continuous Microsoft model updates.

**Current state**: the flag is wired but the Azure backend is not yet implemented. The regex-based provider (`GUARDRAILS_INJECTION_PROVIDER=regex`) remains the active path.

**When to enable this**: in production deployments handling untrusted end users at scale, especially if the eval suite shows the regex layer missing novel phrasing. The API adds latency (~100–200 ms per request); gate it behind `GUARDRAILS_BLOCK_ON_INJECTION` to avoid blocking on false positives during rollout.

**Implementation sketch** (not yet merged):

```python
# shared/guardrails/injection_middleware.py — proposed extension
if settings.GUARDRAILS_INJECTION_PROVIDER == "azure-content-safety":
    from shared.guardrails.azure_shield import check_prompt_shields
    flagged = await check_prompt_shields(messages)
else:
    flagged = any(contains_injection_markers(m.text) for m in messages)
```

---

## Production Hardening Checklist

| Item | Config / Action |
|------|----------------|
| Rotate `JWT_SECRET` | Set to a 256-bit random value; store in Azure Key Vault |
| Rotate `AGENT_SHARED_SECRET` | Same rotation cadence; inject via Managed Identity or Key Vault reference |
| Enable strict identity | `GUARDRAILS_STRICT_IDENTITY=true` |
| Enable fail-closed sanitization | `GUARDRAILS_FAIL_OPEN=false` |
| Evaluate blocking on injection | `GUARDRAILS_BLOCK_ON_INJECTION=true` after measuring false-positive rate in staging |
| Enable HTTPS everywhere | TLS termination at the AKS ingress; no plain HTTP between pods |
| Network policy | Restrict specialist ports (8081–8085) to orchestrator pod only |
| Complete role enforcement | Add `@requires_role` on open items in the [audit matrix](agent-audit-matrix.md) |

---

## Related documents

- [`docs/agent-audit-matrix.md`](agent-audit-matrix.md) — per-agent security status and open items
- [`docs/agent-quality.md`](agent-quality.md) — eval methodology and red-team suite
- [`docs/maf-best-practices.md`](maf-best-practices.md) — MAF idioms used across all agents
- [`docs/architecture.md`](architecture.md) — full system architecture
