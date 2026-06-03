# ECommerceAgents — .NET Port

Port of the Python backend at `../agents/` to .NET 9 using Microsoft Agent Framework.

Both stacks share:
- Postgres schema at `../docker/postgres/init.sql`
- Prompt YAML at `../agents/config/prompts/`
- Seed data produced by `../scripts/seed.py`
- Next.js frontend at `../web/` (selects backend via `NEXT_PUBLIC_BACKEND_STACK=python|dotnet`)

## Projects

| Project | Port | Description |
|---------|------|-------------|
| `src/ECommerceAgents.Shared` | library | Config, auth, telemetry, context providers, prompt loader, DB pool |
| `src/ECommerceAgents.Orchestrator` | 8080 | ASP.NET Core minimal API; HandoffBuilder-based routing |
| `src/ECommerceAgents.ProductDiscovery` | 8081 | Product catalog agent |
| `src/ECommerceAgents.OrderManagement` | 8082 | Order lifecycle agent |
| `src/ECommerceAgents.PricingPromotions` | 8083 | Pricing + coupon agent |
| `src/ECommerceAgents.ReviewSentiment` | 8084 | Review summarization agent |
| `src/ECommerceAgents.InventoryFulfillment` | 8085 | Inventory + shipping agent |

Test projects mirror each under `tests/`.

## Build + test

```bash
cd dotnet
dotnet restore
dotnet build
dotnet test
```

## Run the full .NET stack

```bash
# From repo root
docker compose -f docker-compose.dotnet.yml up --build
```

The Next.js frontend at `http://localhost:3000` will talk to the .NET orchestrator at `:8080` when `NEXT_PUBLIC_BACKEND_STACK=dotnet`.

## Central package management

All package versions live in `Directory.Packages.props` at this folder root. Individual `.csproj` files use `<PackageReference Include="..." />` without a `Version=` attribute.

## Status

The .NET port is functionally complete and at parity with the Python backend. All six specialist agents plus an MCP server are implemented, along with the full shared layer: A2A client/host, JWT auth middleware, tool audit logging, PII redaction, checkpoint storage (in-memory, file, and Postgres backends), declarative workflow primitives, and config validation.

Nine test projects mirror the source structure — one per agent plus Shared and MCP — with ~191 test methods covering tools, middleware, auth, and A2A protocol behavior. The same PostgreSQL schema and A2A wire format are used across both stacks; you can point the frontend at either backend by setting `NEXT_PUBLIC_BACKEND_STACK=dotnet`.

Enhancement plans are tracked in [`.claude/plans/enhancements/`](../../.claude/plans/enhancements/).
