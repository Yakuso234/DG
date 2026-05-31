# E-Commerce Agents

[![Tests](https://github.com/nitin27may/e-commerce-agents/actions/workflows/tests.yml/badge.svg)](https://github.com/nitin27may/e-commerce-agents/actions/workflows/tests.yml)
[![Build Images](https://github.com/nitin27may/e-commerce-agents/actions/workflows/build-images.yml/badge.svg)](https://github.com/nitin27may/e-commerce-agents/actions/workflows/build-images.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://python.org)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000.svg)](https://nextjs.org)
[![MAF v1](https://img.shields.io/badge/Microsoft%20Agent%20Framework-v1-5E5DF0.svg)](https://github.com/microsoft/agent-framework)
[![PostgreSQL + pgvector](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)

A **multi-agent e-commerce platform** built with [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (MAF) Python SDK. Six specialized AI agents collaborate via **A2A protocol** to handle product discovery, orders, pricing, reviews, inventory, and customer support.

Companion demo repo for the AI article series on [nitinksingh.com](https://nitinksingh.com).

![AI shopping assistant with product cards](docs/images/shop-ai-assistant.png)

---

## Where to start

| I want to... | Go here |
|---|---|
| Run the demo locally | [Quick Start](#quick-start) below |
| Understand how the agents work / add a new one | [Architecture](docs/architecture.md) · [Adding an Agent](docs/adding-an-agent.md) |
| Use the MCP server | [MCP Integration](docs/mcp-integration.md) |
| Follow the step-by-step tutorial series | [tutorials/README.md](./tutorials/README.md) |

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [OpenAI API key](https://platform.openai.com/api-keys) (or Azure OpenAI credentials)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/nitin27may/e-commerce-agents.git
cd e-commerce-agents

# 2. Configure environment
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY (or Azure OpenAI credentials)

# 3. Start everything (builds, seeds, and starts all services)
./scripts/dev.sh
```

Open in your browser:
- **Frontend**: http://localhost:3000
- **Aspire Dashboard** (telemetry): http://localhost:18888

### Other Commands

```bash
./scripts/dev.sh --clean       # Nuke volumes, rebuild from scratch
./scripts/dev.sh --seed-only   # Re-run database seeder only
./scripts/dev.sh --infra-only  # Start db + redis + aspire only
```

---

## Table of Contents

- [Project Status](#project-status)
- [Learning Path](#learning-path--maf-v1-python-and-net)
- [Architecture](#architecture)
- [Screens](#screens)
- [Test Users](#test-users)
- [Agent Catalog](#agent-catalog)
- [Demo Scenarios](#demo-scenarios)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Port Map](#port-map)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Project Status

**This is v1 — the Python version is live today.** It runs end-to-end: six specialist agents, orchestrator, auth, telemetry, and a full Next.js frontend.

The frontend is a **public, agentic e-commerce storefront**: anyone can browse the catalog, search, and use the AI shopping assistant (`/shop`) without an account — product discovery is served anonymously — while account flows (cart checkout, orders, tracking, returns) require sign-in. A built-in **agent-activity timeline** surfaces the multi-agent routing (orchestrator → specialist → tool) live in chat, backed by OpenTelemetry → .NET Aspire. Light/dark theming throughout.

The **.NET / C# port** for teams building in the Microsoft ecosystem lives at [`agents/dotnet/`](./agents/dotnet/) alongside the Python backend at [`agents/python/`](./agents/python/). Enhancement plans and the phased roadmap are tracked in [`.claude/plans/enhancements/`](./.claude/plans/enhancements/).

---

## Learning Path — *MAF v1: Python and .NET*

A new step-by-step tutorial series walks through **every Microsoft Agent Framework concept** — agents, tools, memory, middleware, workflow primitives, all five orchestration patterns, HITL, checkpoints, declarative workflows, visualization — with runnable examples in **both Python and .NET**. This repository is the capstone.

**Start here:** [`tutorials/README.md`](./tutorials/README.md)

| Tier | Chapters | Topics |
|------|----------|--------|
| 1 · Core Agent | [01–04](./tutorials/) | First agent · tools · streaming · sessions |
| 2 · Agent Internals | 05–08 | Context providers · middleware · OpenTelemetry · MCP |
| 3 · Workflow Foundations | 09–11 | Executors · edges · events · builder · agents in workflows |
| 4 · Orchestrations | 12–16 | Sequential · Concurrent · Handoff · Group Chat · Magentic |
| 5 · Advanced | 17–20 | HITL · checkpoints · declarative YAML · visualization |
| Capstone | 21 | Guided tour of this repo |

Each chapter has `python/`, `dotnet/`, `tests/`, a Hugo-ready article draft (`README.md`), and a per-chapter plan (`PLAN.md`). Chapters cross-post to [nitinksingh.com](https://nitinksingh.com) under the *MAF v1: Python and .NET* series, complementing the [original Python-only series](https://nitinksingh.com/posts/building-a-multi-agent-e-commerce-platform-the-complete-guide/).

---

## Architecture

![System Architecture](docs/architecture.png)

<details>
<summary>View as Mermaid diagram</summary>

```mermaid
graph TB
    subgraph Client["Browser / Client"]
        FE["Next.js 16<br/>React 19 + Tailwind CSS"]
    end

    subgraph Orchestrator["Orchestrator Agent :8080"]
        FA["FastAPI + MAF"]
        AUTH["JWT Auth + RBAC"]
        ROUTER["Intent Router"]
        CONV["Conversation Mgmt"]
        MKT["Marketplace API"]
    end

    subgraph Specialists["Specialist Agents · A2A Protocol"]
        PD["Product Discovery<br/>:8081"]
        OM["Order Management<br/>:8082"]
        PP["Pricing &amp; Promotions<br/>:8083"]
        RS["Review &amp; Sentiment<br/>:8084"]
        IF["Inventory &amp; Fulfillment<br/>:8085"]
    end

    subgraph Infrastructure["Shared Infrastructure"]
        PG[("PostgreSQL 16<br/>+ pgvector")]
        RD[("Redis 7")]
        ASP["Aspire Dashboard<br/>:18888"]
    end

    subgraph LLM["LLM Provider"]
        OAI["OpenAI API<br/>gpt-4.1"]
        AZ["Azure OpenAI<br/>(configurable)"]
    end

    FE -->|"HTTP/JSON"| FA
    FA --> AUTH
    AUTH --> ROUTER
    ROUTER -->|"A2A"| PD
    ROUTER -->|"A2A"| OM
    ROUTER -->|"A2A"| PP
    ROUTER -->|"A2A"| RS
    ROUTER -->|"A2A"| IF

    PD --> PG
    OM --> PG
    PP --> PG
    RS --> PG
    IF --> PG

    PD -->|"Embeddings"| OAI
    PD -.->|"or"| AZ
    Orchestrator --> RD
    Specialists -->|"OTLP"| ASP

    Orchestrator -->|"OTLP"| ASP
    Specialists --> OAI
    Specialists -.-> AZ

    style Client fill:#6366f1,stroke:#4f46e5,stroke-width:2px,color:#fff
    style FE fill:#818cf8,stroke:#6366f1,color:#fff

    style Orchestrator fill:#0891b2,stroke:#0e7490,stroke-width:2px,color:#fff
    style FA fill:#22d3ee,stroke:#06b6d4,color:#0c4a6e
    style AUTH fill:#fca5a5,stroke:#f87171,color:#7f1d1d
    style ROUTER fill:#67e8f9,stroke:#22d3ee,color:#0c4a6e
    style CONV fill:#67e8f9,stroke:#22d3ee,color:#0c4a6e
    style MKT fill:#67e8f9,stroke:#22d3ee,color:#0c4a6e

    style Specialists fill:#0d9488,stroke:#0f766e,stroke-width:2px,color:#fff
    style PD fill:#2dd4bf,stroke:#14b8a6,color:#134e4a
    style OM fill:#2dd4bf,stroke:#14b8a6,color:#134e4a
    style PP fill:#2dd4bf,stroke:#14b8a6,color:#134e4a
    style RS fill:#2dd4bf,stroke:#14b8a6,color:#134e4a
    style IF fill:#2dd4bf,stroke:#14b8a6,color:#134e4a

    style Infrastructure fill:#475569,stroke:#334155,stroke-width:2px,color:#fff
    style PG fill:#94a3b8,stroke:#64748b,color:#1e293b
    style RD fill:#94a3b8,stroke:#64748b,color:#1e293b
    style ASP fill:#94a3b8,stroke:#64748b,color:#1e293b

    style LLM fill:#d97706,stroke:#b45309,stroke-width:2px,color:#fff
    style OAI fill:#fbbf24,stroke:#f59e0b,color:#78350f
    style AZ fill:#fbbf24,stroke:#f59e0b,color:#78350f
```
</details>

---

## Screens

<table>
<tr>
  <td><img src="docs/images/shop-ai-assistant.png" alt="AI shopping assistant with product cards" width="400"/></td>
  <td><img src="docs/images/agent-timeline.png" alt="Live agent activity timeline" width="400"/></td>
</tr>
<tr>
  <td align="center"><em>AI shopping assistant with product cards</em></td>
  <td align="center"><em>Live agent activity timeline (orchestrator → specialist → tool)</em></td>
</tr>
<tr>
  <td><img src="docs/images/storefront.png" alt="Product storefront" width="400"/></td>
  <td><img src="docs/images/marketplace.png" alt="Agent marketplace" width="400"/></td>
</tr>
<tr>
  <td align="center"><em>Product storefront</em></td>
  <td align="center"><em>Agent marketplace</em></td>
</tr>
<tr>
  <td><img src="docs/images/admin-dashboard.png" alt="Admin dashboard" width="400"/></td>
  <td><img src="docs/images/seller-dashboard.png" alt="Seller dashboard" width="400"/></td>
</tr>
<tr>
  <td align="center"><em>Admin dashboard</em></td>
  <td align="center"><em>Seller dashboard</em></td>
</tr>
</table>

---

## Test Users

Pre-seeded accounts for testing different roles:

| Email | Password | Role | Loyalty Tier |
|-------|----------|------|-------------|
| `admin.demo@gmail.com` | admin123 | Admin | Gold |
| `power.demo@gmail.com` | power123 | Power User | Gold |
| `seller.demo@gmail.com` | seller123 | Seller | Bronze |
| `alice.johnson@gmail.com` | customer123 | Customer | Gold |
| `bob.smith@gmail.com` | customer123 | Customer | Silver |

---

## Agent Catalog

| Agent | Port | Description | Key Tools |
|-------|------|-------------|-----------|
| **Customer Support** (Orchestrator) | 8080 | Routes requests to specialists via A2A | `call_specialist_agent` |
| **Product Discovery** | 8081 | Search, semantic search, comparisons, trending | `search_products`, `semantic_search`, `compare_products` |
| **Order Management** | 8082 | Order tracking, cancellation, returns, refunds | `get_user_orders`, `cancel_order`, `initiate_return` |
| **Pricing & Promotions** | 8083 | Coupon validation, cart optimization, loyalty | `validate_coupon`, `optimize_cart`, `get_active_deals` |
| **Review & Sentiment** | 8084 | Sentiment analysis, fake review detection | `analyze_sentiment`, `detect_fake_reviews` |
| **Inventory & Fulfillment** | 8085 | Stock, shipping estimates, fulfillment planning | `check_stock`, `estimate_shipping` |

---

## Demo Scenarios

Try these in the chat after logging in:

1. **Product Search**: "Find me wireless headphones under $300 with good noise cancellation"
2. **Comparison**: "Compare the Sony WH-1000XM5 with AirPods Max"
3. **Order Tracking**: "Where's my latest order?"
4. **Return Flow**: "I want to return my last order"
5. **Price Check**: "Is the Logitech MX Master 3S a good deal right now?"
6. **Review Analysis**: "What do people think about the Dyson V15?"
7. **Stock Check**: "Is the Dyson V15 Detect in stock?"
8. **Multi-Intent**: "Return my jacket and find me a warmer one under $200"

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Framework | [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) v1.0 (Python SDK) |
| Agent Communication | A2A Protocol (HTTP) |
| LLM | OpenAI / Azure OpenAI (gpt-4.1) |
| Orchestrator | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 + pgvector (1536-dim embeddings) |
| Cache | Redis 7 |
| Frontend | Next.js 16, React 19, Tailwind CSS, shadcn/ui |
| Auth | Self-contained JWT (PyJWT + bcrypt) |
| Telemetry | OpenTelemetry → .NET Aspire Dashboard |
| Package Managers | uv (Python), pnpm (Node) |
| Containerization | Docker Compose |

---

## Project Structure

```
e-commerce-agents/
├── docker-compose.yml               # 11 services with profiles
├── .env.example                     # Environment template
├── agents/                          # Both backends live here
│   ├── python/                      # Python backend
│   │   ├── Dockerfile               # Multi-target (ARG AGENT_NAME)
│   │   ├── pyproject.toml           # Dependencies (MAF, OTel, FastAPI)
│   │   ├── shared/                  # Shared library (config, auth, DB, prompts, telemetry)
│   │   ├── mcp_servers/             # Optional MCP servers (flag-gated via MCP_ENABLED)
│   │   ├── config/prompts/          # YAML prompt configs (shared with .NET)
│   │   ├── orchestrator/            # Customer Support (:8080)
│   │   ├── product_discovery/       # Product Discovery (:8081)
│   │   ├── order_management/        # Order Management (:8082)
│   │   ├── pricing_promotions/      # Pricing & Promotions (:8083)
│   │   ├── review_sentiment/        # Review & Sentiment (:8084)
│   │   └── inventory_fulfillment/   # Inventory & Fulfillment (:8085)
│   └── dotnet/                      # .NET backend — parity with Python
│       ├── ECommerceAgents.sln
│       ├── Directory.Packages.props # Central package versions
│       └── src/
│           ├── ECommerceAgents.Shared/
│           ├── ECommerceAgents.Orchestrator/   # :8080
│           ├── ECommerceAgents.ProductDiscovery/
│           ├── ECommerceAgents.OrderManagement/
│           ├── ECommerceAgents.PricingPromotions/
│           ├── ECommerceAgents.ReviewSentiment/
│           └── ECommerceAgents.InventoryFulfillment/
├── docker/postgres/
│   └── init.sql                    # 24-table schema + pgvector
├── scripts/
│   ├── dev.sh                      # One-command dev setup
│   ├── seed.py                     # Database seeder
│   └── generate_embeddings.py      # Product embedding generation
├── web/                            # Next.js 16 frontend
│   └── src/
│       ├── app/                    # 16 routes (App Router)
│       ├── components/             # UI components (shadcn/ui)
│       └── lib/                    # API client, auth context
├── tutorials/                      # 22-chapter MAF v1 tutorial series (Python + .NET)
└── docs/                           # Full documentation — see docs/README.md
    ├── README.md                   # Docs index and reading order
    ├── architecture.md             # System design, agent patterns, A2A protocol
    ├── adding-an-agent.md          # Step-by-step guide to adding a specialist
    ├── api-reference.md            # All REST endpoints with examples
    ├── agent-flows.md              # Multi-agent collaboration sequence diagrams
    ├── database-schema.md          # 24 tables with ER diagram
    ├── deployment.md               # Docker Compose, dev.sh, environment config
    ├── frontend.md                 # Routes, theming, SSE/timeline, auth model
    ├── telemetry.md                # OpenTelemetry setup and Aspire Dashboard
    ├── mcp-integration.md          # MCP servers, setup, agent wiring
    ├── maf-best-practices.md       # MAF idioms: @tool, middleware, prompt YAML
    ├── security-guide.md           # Threat model, guardrails, hardening checklist
    ├── agent-quality.md            # Eval methodology, datasets, CI gate
    ├── agent-audit-matrix.md       # Per-agent security posture matrix
    └── troubleshooting.md          # Common local-stack issues and fixes
```

---

## Configuration

Copy `.env.example` to `.env` and configure your LLM provider:

```bash
# OpenAI (default)
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4.1

# Azure OpenAI (alternative)
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
```

See [Deployment Guide](docs/deployment.md) for all configuration options.

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design, agent patterns, A2A protocol, auth flow |
| [Adding an Agent](docs/adding-an-agent.md) | Step-by-step guide to adding a specialist agent |
| [API Reference](docs/api-reference.md) | All REST endpoints with examples |
| [Database Schema](docs/database-schema.md) | 24 tables with ER diagram |
| [Telemetry](docs/telemetry.md) | OpenTelemetry setup and Aspire Dashboard |
| [Agent Flows](docs/agent-flows.md) | Multi-agent collaboration diagrams |
| [Deployment](docs/deployment.md) | Docker Compose, dev.sh, environment configuration |
| [Frontend](docs/frontend.md) | Routes, theming, SSE/timeline, public-vs-auth model |
| [Troubleshooting](docs/troubleshooting.md) | Common local-stack issues and fixes |
| [Contributing](CONTRIBUTING.md) | Setup, conventions, testing policy, PR checklist |
| [Security Guide](docs/security-guide.md) | Threat model, guardrails stack, auth, SQL controls |
| [Agent Quality & Evals](docs/agent-quality.md) | Eval methodology, datasets, red-team suite, CI gate |
| [Agent Audit Matrix](docs/agent-audit-matrix.md) | Per-agent security posture and open hardening items |
| [MAF Best Practices](docs/maf-best-practices.md) | MAF idioms: @tool, middleware, prompt YAML, ContextVars |
| [MCP Integration](docs/mcp-integration.md) | MCP servers (FastMCP), MCPStreamableHTTPTool wiring, enable/disable |

---

## Port Map

| Service | Port | URL |
|---------|------|-----|
| Frontend | 3000 | http://localhost:3000 |
| Orchestrator | 8080 | http://localhost:8080 |
| Product Discovery | 8081 | |
| Order Management | 8082 | |
| Pricing & Promotions | 8083 | |
| Review & Sentiment | 8084 | |
| Inventory & Fulfillment | 8085 | |
| Aspire Dashboard | 18888 | http://localhost:18888 |
| PostgreSQL | 5432 | |
| Redis | 6379 | |
| MCP Product | 9000 | http://localhost:9000/mcp (when `--profile mcp`) |
| MCP Inventory | 9001 | http://localhost:9001/mcp (when `--profile mcp`) |

---

## Roadmap

This is v1. The Python platform is live and stable. Several high-impact capabilities are actively in progress.

Legend: `- [x]` shipped · `- [ ]` planned or in progress.

### In Progress — Coming Soon

- [ ] **Agent evaluators** `In progress` — automated response-quality measurement across every specialist. Scripted eval sets (precision@k, recall@k, answer faithfulness, tool-call correctness) run against the seeded catalog with nightly CI gating.
- [ ] **Prompt injection prevention** `In progress` — input classification, system-prompt isolation, tool-allow-listing per role, and output filtering before any user-facing render.
- [ ] **Session memory & context persistence** `In progress` — per-user preferences, recent intents, and past orders surfaced to the orchestrator via a dedicated memory tool, so follow-ups feel continuous.
- [ ] **Human-in-the-loop approval flows** `In progress` — explicit approval gates for high-stakes actions (refunds over threshold, inventory writes, bulk price changes). The agent pauses, renders an approval card in the UI, and proceeds once the operator confirms.
- [ ] **Per-agent cost tracking** `In progress` — token spend and dollar cost per specialist, per tool call, per user session as first-class OpenTelemetry metrics.
- [ ] **Full .NET / C# port** `In progress` — same six agents, same A2A protocol, same PostgreSQL schema — idiomatic .NET throughout.

> **Status:** the Python version is live today. The .NET version is coming.

---

### Planned — Search & Retrieval

The product catalog has 1536-dim pgvector embeddings but `search_products` still uses `ILIKE` matching. Planned:

- [ ] **Postgres full-text search** — `tsvector` column + GIN index, `plainto_tsquery` + `ts_rank` to replace the `ILIKE` loop.
- [ ] **Hybrid retrieval (FTS + vector)** — combine lexical and semantic scores via Reciprocal Rank Fusion in a single CTE.
- [ ] **Smarter tool routing** — update `product-discovery.yaml` so the LLM routes vague descriptive queries to `semantic_search` and attribute-driven queries to `search_products`.
- [ ] **Typed filter DSL** — replace the flat parameter list on `search_products` with a structured `ProductFilters` Pydantic model (category, price, brand, sort). Keeps SQL parameterized and safe.

Text-to-SQL was considered and rejected: `user_email`/`user_role` scoping via ContextVars means dynamic SQL would bypass that contract. The typed filter DSL gives the model flexibility at the boundary while keeping SQL generation server-side and auditable.

---

### Planned — MCP as the Agent Data-Access Layer

Two MCP servers are live today, flag-gated behind `MCP_ENABLED`:

- `mcp-product` on port 9000 — product search, details, comparison, price history
- `mcp-inventory` on port 9001 — stock levels, warehouses, shipping, carriers

See [MCP Integration](docs/mcp-integration.md) for the full setup guide and how to inspect the servers.

Planned next:

- [ ] **Expand MCP surface** — port `order_tools`, `pricing_tools`, `cart_tools`, and `review_tools` into MCP servers so all five specialists have a portable, language-agnostic data layer.
- [ ] **External integration surface** — any MCP-compatible client (Claude Desktop, Cursor, LangGraph) can consume the same tools the internal specialists use, with identical auth and observability.
- [ ] **Eval gate** — run each eval dataset twice (native tools vs MCP path) and fail CI if the MCP run scores below the native baseline.

---

### Planned — Platform & Observability

- [ ] **Prompt caching** — cache system prompts and tool schemas per agent to reduce per-request token cost on repeated specialist invocations.
- [ ] **Streaming tool calls end-to-end** `In progress` — propagate partial tool results over SSE so the UI renders product cards as they arrive.
- [x] **Observability dashboards** — pre-built Aspire Dashboard views for agent latency, tool error rates, and LLM token spend per specialist.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes and ensure tests pass
4. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed setup, conventions, testing policy, and PR checklist.

---

## License

This project is licensed under the [MIT License](LICENSE).

---

Built with [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) and [A2A Protocol](https://google.github.io/A2A/).
