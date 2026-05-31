# Agent Security Audit Matrix

Per-agent snapshot of the current security posture and the remaining hardening targets.
This matrix is the anchor reference for [`docs/security-guide.md`](security-guide.md) and
[`docs/agent-quality.md`](agent-quality.md).

**Legend**

| Symbol | Meaning |
|--------|---------|
| Done | Implemented and verified in tests |
| Partial | Present but incomplete (noted inline) |
| Target | Not yet implemented; tracked as a follow-up |

---

## Dimensions

| # | Dimension | What it covers |
|---|-----------|---------------|
| 1 | **Injection defense — inbound** | `InjectionDetectionChatMiddleware` scanning user messages before they reach the model |
| 2 | **Injection defense — stored** | `OutputSanitizationMiddleware` neutralizing tool results that carry user-generated text before it re-enters the model |
| 3 | **Role enforcement** | `@requires_role` / `ensure_role` checks on destructive or privileged tools |
| 4 | **Eval dataset** | Named dataset file under `agents/python/evals/datasets/` |
| 5 | **Red-team coverage** | Attack vectors from `red_team.json` that target this agent |

---

## Matrix

### Orchestrator (`orchestrator`, port 8080)

**Role**: Front door. Routes all user requests to specialist agents via `call_specialist_agent`. No domain tools; LLM output is a routing instruction, not user-facing data.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` in `build_specialist_middleware()` |
| Stored-content sanitization | N/A | No tools that return user-generated free text |
| Role enforcement | N/A | No domain tools; routing only |
| Eval dataset | Done | `datasets/orchestrator_routing.json` — 6 intent/routing cases |
| Red-team coverage | Done | `red_team.json`: jailbreak (DAN prompt), instruction-override injection |

**Target**: None — current posture matches the agent's narrow scope.

---

### Product Discovery (`product-discovery`, port 8081)

**Role**: Natural language product search, semantic similarity, price history, trending products.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` |
| Stored-content sanitization | Done | `search_products`, `get_product_details`, `find_similar_products`, `semantic_search`, `get_trending_products` all covered in `guardrails/config.py:SANITIZE_TOOLS` |
| Role enforcement | N/A | All current tools are public; no privileged operations |
| Eval dataset | Done | `datasets/product_discovery.json` |
| Red-team coverage | Done | `red_team.json`: embedded-token injection (`PWNED-1337`) via product search |

**Target**: If seller-only product-management tools are added (create/update product), gate them with `@requires_role("seller", "admin")`.

---

### Order Management (`order-management`, port 8082)

**Role**: Order tracking, cancellation, modification, returns, refunds, cart operations.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` |
| Stored-content sanitization | Done | `get_order_details`, `get_user_orders` covered in `SANITIZE_TOOLS` (fields: `note`, `notes`, `reason`) |
| Role enforcement | Partial | SQL-layer ownership filter (`WHERE u.email = $2`) prevents cross-user reads, but `cancel_order`, `process_refund`, `modify_order` have no explicit role gate |
| Eval dataset | Done | `datasets/order_management.json` |
| Red-team coverage | Done | `red_team.json`: role escalation (fetch all users' orders; expose another user's address) |

**Target**: Apply `@requires_role("customer", "seller", "admin")` on `cancel_order`, `modify_order`, `process_refund` to prevent unauthenticated tool calls from succeeding even if the ownership SQL filter is ever loosened.

---

### Pricing & Promotions (`pricing-promotions`, port 8083)

**Role**: Coupon validation, cart optimization, loyalty discounts, bundle deals, active promotions.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` |
| Stored-content sanitization | N/A | Tool outputs are structured/numeric (prices, discount amounts, eligibility flags) |
| Role enforcement | Partial | Seller-specific revenue tools in `shared/tools/seller_tools.py` all carry `@requires_role("seller", "admin")`; the pricing agent does not currently expose those tools, but any future addition must carry the decorator |
| Eval dataset | Done | `datasets/pricing_promotions.json` |
| Red-team coverage | Done | `red_team.json`: role escalation (impersonate seller to access revenue/payout data) |

**Target**: If `get_seller_revenue` or similar tools are wired into this agent, they are already decorated; no further action required. Add `ensure_role` guard in any new tool that touches per-seller financials.

---

### Review & Sentiment (`review-sentiment`, port 8084)

**Role**: Review analysis, sentiment breakdown, fake-review detection, seller response drafting, cross-product comparison.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` — highest-risk agent for inbound injection because user input can request review text |
| Stored-content sanitization | Done | All read tools (`get_product_reviews`, `analyze_sentiment`, `compare_reviews`, `detect_fake_reviews`, `get_review_trends`) covered in `SANITIZE_TOOLS` with explicit field allowlists |
| Role enforcement | Partial | `draft_seller_response` is exposed to all authenticated callers; should be restricted to sellers and admins |
| Eval dataset | Done | `datasets/review_sentiment.json` |
| Red-team coverage | Done | `red_team.json`: two injection attacks — direct system-prompt dump via review request; indirect via embedded "follow it" instruction in review content |

**Target**: Add `@requires_role("seller", "admin")` to `draft_seller_response` in `review_sentiment/tools.py`. This is the highest-priority open item on the matrix.

---

### Inventory & Fulfillment (`inventory-fulfillment`, port 8085)

**Role**: Stock checking, warehouse availability, shipping estimation, carrier comparison, backorder placement.

| Dimension | Status | Detail |
|-----------|--------|--------|
| Inbound injection detection | Done | `InjectionDetectionChatMiddleware` |
| Stored-content sanitization | N/A | Tool outputs are structured (quantities, ETAs, carrier rates) |
| Role enforcement | Target | `place_backorder` and `calculate_fulfillment_plan` are seller/ops operations but carry no role gate |
| Eval dataset | Done | `datasets/inventory_fulfillment.json` |
| Red-team coverage | Done | `red_team.json`: injection via stock-check request attempting secret exfiltration (`AGENT_SHARED_SECRET`) |

**Target**: Apply `@requires_role("seller", "admin")` to `place_backorder` and `calculate_fulfillment_plan` in `inventory_fulfillment/tools.py`.

---

## Summary Table

| Agent | Inbound Inject. | Output Sanitize | Role Enforce | Eval Dataset | Red-team |
|-------|:-----------:|:-----------:|:-----------:|:-----------:|:-----------:|
| orchestrator | Done | N/A | N/A | Done | Done |
| product-discovery | Done | Done | N/A | Done | Done |
| order-management | Done | Done | Partial | Done | Done |
| pricing-promotions | Done | N/A | Partial | Done | Done |
| review-sentiment | Done | Done | **Partial** | Done | Done |
| inventory-fulfillment | Done | N/A | **Target** | Done | Done |

**Open items (priority order)**

1. `review-sentiment` — `draft_seller_response`: add `@requires_role("seller", "admin")`
2. `inventory-fulfillment` — `place_backorder`, `calculate_fulfillment_plan`: add `@requires_role("seller", "admin")`
3. `order-management` — `cancel_order`, `modify_order`, `process_refund`: add `@requires_role("customer", "seller", "admin")`

---

## Related documents

- [`docs/security-guide.md`](security-guide.md) — threat model, guardrails architecture, auth flow, Azure AI Content Safety option
- [`docs/agent-quality.md`](agent-quality.md) — eval philosophy, datasets, CI gate
- [`docs/maf-best-practices.md`](maf-best-practices.md) — MAF idioms and patterns used across all agents
