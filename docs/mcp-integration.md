# MCP Integration

E-Commerce Agents supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) as an optional, flag-gated alternative data layer for the specialist agents.

## What this demonstrates

The default architecture has specialist agents calling PostgreSQL directly via `asyncpg`:

```
Specialist Agent (MAF)
  → @tool function
  → asyncpg
  → PostgreSQL
```

With MCP enabled, the same agents call a running MCP server instead:

```
Specialist Agent (MAF)
  → MCPStreamableHTTPTool (MAF's built-in MCP client)
  → Streamable HTTP (MCP protocol)
  → MCP Server (FastMCP + asyncpg)
  → PostgreSQL
```

The agent's behavior — the prompts, routing, middleware, guardrails — is identical in both modes. Only the data access layer changes. This makes the specialist agents **portable**: any MCP-compatible client (Claude Desktop, another framework, a custom integration) can access the same product and inventory data without knowing anything about this codebase.

## MCP Servers

| Server | Port | Domain | File |
|--------|------|--------|------|
| `mcp-product` | 9000 | Product search, details, comparison, price history | `mcp_servers/product_server.py` |
| `mcp-inventory` | 9001 | Stock levels, warehouses, shipping, carriers | `mcp_servers/inventory_server.py` |

Both use [FastMCP](https://github.com/modelcontextprotocol/python-sdk) and expose the MCP streamable HTTP transport at `/mcp`. MAF's `MCPStreamableHTTPTool` connects to that endpoint.

## Enabling MCP mode

### 1. Start the MCP servers

```bash
# Start MCP servers alongside infrastructure
docker compose --profile mcp --profile agents up
```

Or locally for development:

```bash
cd agents/python

# Product MCP server on :9000
uv run uvicorn mcp_servers.product_server:app --port 9000 --reload &

# Inventory MCP server on :9001
uv run uvicorn mcp_servers.inventory_server:app --port 9001 --reload &
```

### 2. Set environment variables

```bash
MCP_ENABLED=true
MCP_PRODUCT_SERVER_URL=http://localhost:9000/mcp    # or http://mcp-product:9000/mcp in Docker
MCP_INVENTORY_SERVER_URL=http://localhost:9001/mcp  # or http://mcp-inventory:9001/mcp in Docker
```

### 3. Restart the specialist agents

The `product-discovery` and `inventory-fulfillment` agents read `MCP_ENABLED` at startup and select the appropriate tool set. No code changes are needed.

## Inspect with MCP Inspector

The [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) is an interactive tool for testing MCP servers. With the servers running:

```bash
# Inspect the product server
npx @modelcontextprotocol/inspector http://localhost:9000/mcp

# Inspect the inventory server
npx @modelcontextprotocol/inspector http://localhost:9001/mcp
```

This lets you browse the tool schemas, call individual tools, and see the raw MCP protocol messages.

## How the agent selection works

In `product_discovery/agent.py` and `inventory_fulfillment/agent.py`:

```python
from agent_framework._mcp import MCPStreamableHTTPTool
from shared.config import settings

def create_product_discovery_agent() -> Agent:
    if settings.MCP_ENABLED:
        mcp_product = MCPStreamableHTTPTool(
            name="product-mcp",
            url=settings.MCP_PRODUCT_SERVER_URL,
            description="Product catalog data via MCP",
        )
        tools = [mcp_product, semantic_search, get_price_history, ...]
    else:
        tools = AGENT_TOOLS  # direct asyncpg @tool functions

    return Agent(client=..., tools=tools, ...)
```

`MCPStreamableHTTPTool` is MAF's built-in MCP client. When the agent initializes, it calls the MCP server's tool listing endpoint, discovers the available tools, and exposes them to the LLM exactly like native `@tool` functions. The LLM cannot tell the difference.

## Tool coverage

Not all tools are migrated to MCP. Tools that require user identity context (ContextVars set by the auth middleware) or are unique to this platform (semantic vector search, `place_backorder`) remain as direct `@tool` functions even in MCP mode. The MCP servers cover the pure data-access tools that are genuinely portable.

| Tool | MCP mode | Direct mode |
|------|----------|-------------|
| `search_products` | product-mcp server | asyncpg `@tool` |
| `get_product_details` | product-mcp server | asyncpg `@tool` |
| `compare_products` | product-mcp server | asyncpg `@tool` |
| `get_trending_products` | product-mcp server | asyncpg `@tool` |
| `get_price_history` | product-mcp server | asyncpg `@tool` |
| `semantic_search` | direct `@tool` | asyncpg `@tool` |
| `check_stock` | inventory-mcp server | asyncpg `@tool` |
| `get_warehouse_availability` | inventory-mcp server | asyncpg `@tool` |
| `estimate_shipping` | inventory-mcp server | asyncpg `@tool` |
| `compare_carriers` | inventory-mcp server | asyncpg `@tool` |
| `get_restock_schedule` | inventory-mcp server | asyncpg `@tool` |
| `place_backorder` | direct `@tool` | asyncpg `@tool` |

## Adding a new MCP server

1. Create `mcp_servers/{domain}_server.py` using FastMCP:

```python
from mcp.server.fastmcp import FastMCP
from typing import Annotated

mcp = FastMCP("my-domain-mcp")

@mcp.tool()
async def my_tool(param: Annotated[str, "Description"]) -> dict:
    ...

app = mcp.streamable_http_app()  # ASGI entry-point for uvicorn
```

2. Add the service to `docker-compose.yml` under the `mcp` profile.
3. Add config vars to `shared/config.py` and `.env.example`.
4. Wire `MCPStreamableHTTPTool` into the relevant agent factory.

## Related

- [`docs/architecture.md`](architecture.md) — full system architecture
- [`docs/telemetry.md`](telemetry.md) — OTel + Langfuse observability
- [`docs/maf-best-practices.md`](maf-best-practices.md) — MAF patterns used across all agents
