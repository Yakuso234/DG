"""官方 mcp SDK 的最小读工具服务器 + 内存 transport 调用封装。

服务器用官方 lowlevel Server（on_list_tools / on_call_tool 构造器注入）；
transport 用官方支持的 InMemory 方式：
``mcp.shared.memory.create_client_server_memory_streams()`` —— 两端通过 anyio
内存对象流直连，不经过任何网络。
"""
from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_client_server_memory_streams

MCP_SERVER_NAME = "ticket-mcp"

# 确定性读数据：仅 T-1001 有记录。
_TICKETS: dict[str, dict[str, Any]] = {
    "T-1001": {
        "ticket_id": "T-1001",
        "status": "INVESTIGATING",
        "title": "pipeline stalled",
        "owner": "ops",
    },
}


async def _list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="get_ticket_status",
                description="读取工单当前状态（只读工具）",
                input_schema={
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
            )
        ]
    )


async def _call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    args = params.arguments or {}

    if name != "get_ticket_status":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"unknown tool: {name}")],
            structured_content={
                "error": {"code": "UNKNOWN_TOOL", "message": f"tool {name!r} not found"}
            },
            is_error=True,
        )

    ticket_id = args.get("ticket_id")
    data = _TICKETS.get(ticket_id)
    if data is None:
        # 结构化错误：非空、无堆栈。
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"ticket {ticket_id!r} not found")],
            structured_content={
                "error": {
                    "code": "TICKET_NOT_FOUND",
                    "message": f"ticket_id={ticket_id!r} not found",
                }
            },
            is_error=True,
        )

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=str(data))],
        structured_content=data,
        is_error=False,
    )


def build_ticket_mcp_server() -> Server:
    """构建暴露 get_ticket_status 的最小 MCP 服务器。"""
    return Server(
        MCP_SERVER_NAME,
        version="1.0.0",
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


async def call_ticket_mcp_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """通过官方内存 transport 调一次工具，返回 CallToolResult。"""
    server = build_ticket_mcp_server()
    init_options = server.create_initialization_options()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        server_task = asyncio.create_task(
            server.run(server_streams[0], server_streams[1], init_options)
        )
        try:
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                await session.initialize()
                return await session.call_tool(name, arguments)
        finally:
            server_task.cancel()
            try:
                await server_task
            except BaseException:
                pass


def call_ticket_mcp_tool_sync(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """同步包装：供 LangGraph 同步节点内联调用。"""
    return asyncio.run(call_ticket_mcp_tool(name, arguments))
