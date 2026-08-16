"""FlowPilot — 企业工单处置多 Agent 平台。

Phase 1：工单域与确定性执行核心（无 LLM、无框架依赖）。
本包只包含确定性领域逻辑与数据访问；Agent 运行时按 ADR-001 使用
LangGraph 1.x + 官方 A2A/MCP SDK，将在 Phase 3 接入。
"""

__version__ = "0.1.0"
