"""Inventory & Fulfillment agent definition.

When ``settings.MCP_ENABLED`` is True the agent connects to the Inventory MCP
server (``ecommerce_mcp_inventory.server``) via ``MCPStreamableHTTPTool`` instead
of calling asyncpg directly. Both modes expose the same capabilities.
"""

from agent_framework import Agent
from agent_framework._mcp import MCPStreamableHTTPTool

from inventory_fulfillment.prompts import SYSTEM_PROMPT
from inventory_fulfillment.tools import (
    calculate_fulfillment_plan,
    compare_carriers,
    estimate_shipping,
    get_restock_schedule,
    get_tracking_status,
    place_backorder,
)
from shared.agent_factory import create_chat_client
from shared.config import settings
from shared.context_providers import ECommerceContextProvider
from shared.middleware import build_specialist_middleware
from shared.tools.inventory_tools import check_stock, get_warehouse_availability
from shared.tools.user_tools import get_user_profile

AGENT_TOOLS = [
    check_stock,
    get_warehouse_availability,
    get_restock_schedule,
    estimate_shipping,
    compare_carriers,
    get_tracking_status,
    calculate_fulfillment_plan,
    place_backorder,
    get_user_profile,
]


def create_inventory_fulfillment_agent() -> Agent:
    """Create the Inventory & Fulfillment ChatAgent.

    Uses the MCP server when ``MCP_ENABLED=true``, direct asyncpg tools otherwise.
    """
    if settings.MCP_ENABLED:
        # MCP path: tools are discovered from the running MCP server at startup.
        # Non-MCP tools (tracking, fulfillment plan, backorder, user_profile) still
        # run locally since they are not yet exposed via the MCP server.
        mcp_inventory = MCPStreamableHTTPTool(
            name="inventory-mcp",
            url=settings.MCP_INVENTORY_SERVER_URL,
            description="Inventory and fulfillment data via MCP",
        )
        tools: list = [
            mcp_inventory,
            get_tracking_status,
            calculate_fulfillment_plan,
            place_backorder,
            get_user_profile,
        ]
    else:
        tools = AGENT_TOOLS  # type: ignore[assignment]

    return Agent(
        client=create_chat_client(),
        name="inventory-fulfillment",
        description="Real-time inventory tracking, shipping estimation, carrier comparison, and backorder management.",
        instructions=SYSTEM_PROMPT,
        tools=tools,
        context_providers=[ECommerceContextProvider()],
        middleware=build_specialist_middleware(),
    )
