"""Product Discovery agent definition.

When ``settings.MCP_ENABLED`` is True the agent connects to the Product MCP
server (``ecommerce_mcp_product.server``) via ``MCPStreamableHTTPTool`` instead
of calling asyncpg directly. Both modes expose the same capabilities.
"""

from agent_framework import Agent
from agent_framework._mcp import MCPStreamableHTTPTool

from product_discovery.prompts import SYSTEM_PROMPT
from product_discovery.tools import (
    compare_products,
    find_similar_products,
    get_product_details,
    get_trending_products,
    search_products,
    semantic_search,
)
from shared.agent_factory import create_chat_client
from shared.config import settings
from shared.context_providers import ECommerceContextProvider
from shared.middleware import build_specialist_middleware
from shared.tools.inventory_tools import check_stock, get_warehouse_availability
from shared.tools.pricing_tools import get_price_history
from shared.tools.memory_tools import recall_memories, store_memory
from shared.tools.user_tools import get_purchase_history, get_user_profile

AGENT_TOOLS = [
    search_products,
    get_product_details,
    compare_products,
    semantic_search,
    find_similar_products,
    get_trending_products,
    check_stock,
    get_warehouse_availability,
    get_price_history,
    get_user_profile,
    get_purchase_history,
    store_memory,
    recall_memories,
]


def create_product_discovery_agent() -> Agent:
    """Create the Product Discovery ChatAgent.

    Uses the MCP server when ``MCP_ENABLED=true``, direct asyncpg tools otherwise.
    """
    if settings.MCP_ENABLED:
        # MCP path: core product tools come from the MCP server.
        # Semantic search, price history, and user tools still run locally
        # since they depend on pgvector / user context not yet in the MCP server.
        mcp_product = MCPStreamableHTTPTool(
            name="product-mcp",
            url=settings.MCP_PRODUCT_SERVER_URL,
            description="Product catalog data via MCP",
        )
        tools: list = [
            mcp_product,
            semantic_search,
            find_similar_products,
            get_price_history,
            check_stock,
            get_user_profile,
            get_purchase_history,
        ]
    else:
        tools = AGENT_TOOLS  # type: ignore[assignment]

    return Agent(
        client=create_chat_client(),
        name="product-discovery",
        description="Natural language product search, semantic similarity, recommendations, and price tracking.",
        instructions=SYSTEM_PROMPT,
        tools=tools,
        context_providers=[ECommerceContextProvider()],
        middleware=build_specialist_middleware(),
    )
