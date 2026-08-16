"""Patch agent_framework __init__.py if it's empty (MAF v1.0 packaging bug).

Run this before starting any agent if using agent-framework==1.0.0.
The package ships with an empty __init__.py that doesn't re-export public APIs.
"""

import importlib
import importlib.util
import pathlib

PATCH = '''\
"""Microsoft Agent Framework — re-exports for E-Commerce Agents."""
__version__ = "1.0.0"

from agent_framework._agents import Agent, RawAgent, BaseAgent
from agent_framework._tools import tool, FunctionTool
from agent_framework._types import Message, Content, Role
from agent_framework._clients import BaseChatClient
from agent_framework._sessions import AgentSession, HistoryProvider, InMemoryHistoryProvider, ContextProvider
from agent_framework._mcp import MCPStreamableHTTPTool, MCPStdioTool, MCPTool
'''


def patch() -> None:
    spec = importlib.util.find_spec("agent_framework")
    if spec is None or spec.origin is None:
        raise ModuleNotFoundError("agent_framework is not installed")

    init_path = pathlib.Path(spec.origin)
    try:
        current = init_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        current = ""

    if current.strip() == "":
        init_path.write_text(PATCH, encoding="utf-8")
        import agent_framework

        importlib.reload(agent_framework)
        print(f"Patched {init_path}")


if __name__ == "__main__":
    patch()
