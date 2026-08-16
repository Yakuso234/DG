"""SPIKE-001 B 栈：LangGraph 1.x + 官方 a2a-sdk + 官方 mcp sdk 最小原型。

实现文件（除 spikes/shared/ 与 tests/ 外，即 glue_lines 统计范围）：
  - fake_model.py : 确定性、无网络 Fake Model（合同第 4 节）
  - mcp_tools.py  : 官方 mcp SDK 内存 transport 的读工具服务器
  - graph.py      : LangGraph 1.x 状态机 + 持久化 HITL 图
  - a2a_agent.py  : 官方 a2a-sdk 内存 transport AgentCard + message:send
  - report.py     : report.json 生成（glue_lines / 依赖版本）
"""
