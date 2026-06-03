# MCP Integration

E-Commerce Agents ships two standalone MCP servers as independently publishable Python packages.
They expose product and inventory data over the [Model Context Protocol](https://modelcontextprotocol.io)
streamable HTTP transport so any MCP-compatible client can consume them without knowing anything
about this codebase.

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

The agent's behavior — prompts, routing, middleware, guardrails — is identical in both modes.
Only the data access layer changes.

## MCP Servers

| Server | Port | Domain | Package |
|--------|------|--------|---------|
| `mcp-product` | 9000 | Product search, details, comparison, trending, price history | `packages/mcp-product` |
| `mcp-inventory` | 9001 | Stock levels, warehouses, shipping, carriers | `packages/mcp-inventory` |

Both use [FastMCP](https://github.com/modelcontextprotocol/python-sdk) and expose the MCP streamable
HTTP transport at `/mcp`. MAF's `MCPStreamableHTTPTool` connects to that endpoint.

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
uv run uvicorn ecommerce_mcp_product.server:app --port 9000 --reload &

# Inventory MCP server on :9001
uv run uvicorn ecommerce_mcp_inventory.server:app --port 9001 --reload &
```

### 2. Set environment variables

```bash
MCP_ENABLED=true
MCP_PRODUCT_SERVER_URL=http://localhost:9000/mcp    # or http://mcp-product:9000/mcp in Docker
MCP_INVENTORY_SERVER_URL=http://localhost:9001/mcp  # or http://mcp-inventory:9001/mcp in Docker
```

### 3. Restart the specialist agents

The `product-discovery` and `inventory-fulfillment` agents read `MCP_ENABLED` at startup and
select the appropriate tool set. No code changes are needed.

## Inspect with MCP Inspector

The [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) is an interactive tool
for testing MCP servers. With the servers running:

```bash
# Inspect the product server
npx @modelcontextprotocol/inspector http://localhost:9000/mcp

# Inspect the inventory server
npx @modelcontextprotocol/inspector http://localhost:9001/mcp
```

This lets you browse tool schemas, call individual tools, and see raw MCP protocol messages.

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
        # User-context tools (semantic search, price history) stay local —
        # they depend on pgvector / ContextVars not propagated to the MCP server.
        tools = [mcp_product, semantic_search, find_similar_products, ...]
    else:
        tools = AGENT_TOOLS  # direct asyncpg @tool functions

    return Agent(client=..., tools=tools, ...)
```

`MCPStreamableHTTPTool` is MAF's built-in MCP client. When the agent initialises, it calls the
MCP server's tool listing endpoint, discovers the available tools, and exposes them to the LLM
exactly like native `@tool` functions. The LLM cannot tell the difference.

## Tool coverage

Not all tools are migrated to MCP. Tools that require user identity context (ContextVars set by
the auth middleware) or are unique to this platform (semantic vector search, `place_backorder`)
remain as direct `@tool` functions even in MCP mode. The MCP servers cover pure data-access tools
that are genuinely portable.

| Tool | MCP mode | Direct mode |
|------|----------|-------------|
| `search_products` | product-mcp server | asyncpg `@tool` |
| `get_product_details` | product-mcp server | asyncpg `@tool` |
| `compare_products` | product-mcp server | asyncpg `@tool` |
| `get_trending_products` | product-mcp server | asyncpg `@tool` |
| `get_price_history` | product-mcp server | asyncpg `@tool` |
| `semantic_search` | direct `@tool` (pgvector) | asyncpg `@tool` |
| `find_similar_products` | direct `@tool` (pgvector) | asyncpg `@tool` |
| `check_stock` | inventory-mcp server | asyncpg `@tool` |
| `get_warehouse_availability` | inventory-mcp server | asyncpg `@tool` |
| `estimate_shipping` | inventory-mcp server | asyncpg `@tool` |
| `compare_carriers` | inventory-mcp server | asyncpg `@tool` |
| `get_restock_schedule` | inventory-mcp server | asyncpg `@tool` |
| `get_tracking_status` | direct `@tool` | asyncpg `@tool` |
| `place_backorder` | direct `@tool` | asyncpg `@tool` |

## Package structure

Each MCP server is a standalone Python package under `agents/python/packages/`:

```
agents/python/packages/
  mcp-product/
    pyproject.toml          # name = "ecommerce-mcp-product"
    src/ecommerce_mcp_product/
      server.py             # FastMCP server + ASGI app
    tests/
  mcp-inventory/
    pyproject.toml          # name = "ecommerce-mcp-inventory"
    src/ecommerce_mcp_inventory/
      server.py
    tests/
```

Both are members of the `agents/python` uv workspace. A single `uv.lock` covers the whole
workspace; the MCP packages share resolved deps without re-pinning.

## Publishing a server independently

```bash
cd agents/python

# Build wheel + sdist
uv build --package ecommerce-mcp-product
uv build --package ecommerce-mcp-inventory

# Publish to PyPI (or a private registry)
uv publish dist/ecommerce_mcp_product-*.whl
uv publish dist/ecommerce_mcp_inventory-*.whl
```

Once published, any MCP client can install and run the server without the rest of this repo:

```bash
pip install ecommerce-mcp-product
DATABASE_URL=postgresql://... ecommerce-mcp-product   # starts on :9000
```

## Adding a new MCP server

1. Create a new workspace package:

```bash
mkdir -p agents/python/packages/mcp-<domain>/src/ecommerce_mcp_<domain>
```

2. Add `pyproject.toml` mirroring the existing packages (name `ecommerce-mcp-<domain>`,
   deps `mcp[cli]`, `asyncpg`, `uvicorn`, console script entry-point).

3. Write `server.py` using FastMCP:

```python
from mcp.server.fastmcp import FastMCP
from typing import Annotated

mcp = FastMCP("my-domain-mcp", lifespan=_lifespan)

@mcp.tool()
async def my_tool(param: Annotated[str, "Description"]) -> dict:
    ...

app = mcp.streamable_http_app()  # ASGI entry-point for uvicorn
```

4. Register the package in the workspace root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["packages/mcp-product", "packages/mcp-inventory", "packages/mcp-<domain>"]
```

5. Run `uv lock` to update the shared lockfile.

6. Add a service to `docker-compose.yml` under the `mcp` profile using `Dockerfile.mcp`.

7. Add config vars to `shared/config.py` and `.env.example`.

8. Wire `MCPStreamableHTTPTool` into the relevant agent factory.

## Using from external MCP clients

Because these are standard MCP servers, any MCP-compatible client can connect:

```json
// Claude Desktop — claude_desktop_config.json
{
  "mcpServers": {
    "ecommerce-product": {
      "command": "ecommerce-mcp-product",
      "env": { "DATABASE_URL": "postgresql://..." }
    },
    "ecommerce-inventory": {
      "command": "ecommerce-mcp-inventory",
      "env": { "DATABASE_URL": "postgresql://..." }
    }
  }
}
```

```python
# LangGraph / LangChain
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "product": {"url": "http://localhost:9000/mcp", "transport": "streamable_http"},
    "inventory": {"url": "http://localhost:9001/mcp", "transport": "streamable_http"},
})
```

## Related

- [`docs/architecture.md`](architecture.md) — full system architecture
- [`docs/telemetry.md`](telemetry.md) — OTel + Langfuse observability
- [`docs/maf-best-practices.md`](maf-best-practices.md) — MAF patterns used across all agents
