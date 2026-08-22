# DG / FlowPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Workflow-LangGraph-1f2937.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2016-336791.svg)](https://www.postgresql.org/)

DG / FlowPilot 是一个面向企业故障处置的 Python 多 Agent 控制平面，也是我秋招后端 / Python Agent 应用开发岗位重构的个人项目。它把 Agent 置于明确的业务与安全边界中：Agent 负责调查和提出结构化建议；状态机、RBAC、动作合同、审批和幂等由确定性服务端代码负责。

第一条闭环围绕“短视频处理任务卡住”：创建工单 → 调查外部状态 → 生成恢复提案 → 风险复核 → 人工审批 → 受控执行 → 审计与运行轨迹查询。

> 这是对上游开源项目的授权重构与扩展，不是对其电商功能的简单复述。上游电商模块仍作为迁移参考底座，不能视为 FlowPilot 的已完成能力。

## 我完成的重构与贡献

### 1. 将电商 Demo 收敛为可面试、可验证的工单处置主线

- 定义 `Ticket`、`Evidence`、`ActionProposal`、`Approval`、`ExecutionRecord` 与 `AgentRun` 等领域对象。
- 用显式状态机约束 `NEW → TRIAGED → INVESTIGATING → PROPOSED → WAITING_APPROVAL → EXECUTING → RESOLVED`，并保留 `FAILED` / `ESCALATED` 分支。
- 在 PostgreSQL Repository 中实现行锁、版本条件更新、审批冲突处理、业务幂等和同事务审计，避免把 Agent 编排顺序当作数据一致性保障。

### 2. 构建受控 LangGraph Agent 工作流，而非让模型直接执行写操作

```text
FastAPI 请求
  -> LangGraph：Triage -> Investigation -> Resolution -> Risk Review
  -> Evidence / Proposal 持久化
  -> interrupt() 暂停等待人工审批
  -> Command(resume) 恢复
  -> Service Actor 受控执行
  -> PostgreSQL 审计与 Agent Run 摘要
```

- Investigation 通过统一 Gateway 获取带来源和 TraceId 的 Evidence。
- 模型端口只允许提出结构化分诊 / 动作建议；服务端从 Evidence 构造 `ticket_id`、`creator_id`、`video_id`、`trace_id`，并从 `ACTION_CATALOG` 重算风险。
- 高风险恢复动作必须先落审批，再以 service Actor 执行；审批者不能越过职责分离直接执行。

### 3. 建立 MCP、审批恢复与外部动作边界

- 实现 `sw-video-ops-mcp` 的 Streamable HTTP `ClientSession` 调查通道，并保留确定性 Mock transport 用于回归。
- 使用 SQLite checkpoint 持久化审批暂停点；启动与审批 API 共享同一 LangGraph 运行时。
- 实现受限 `recover_expired_video_processing` 动作合同：固定业务范围、服务身份、TraceId、幂等键和严格响应校验。真实 SW 双进程联调仍是后续可选工作，不把 Mock / HTTP 合同测试表述为生产集成。

### 4. 补齐可观测、身份与演示能力

- API 统一生成或透传 `X-Trace-Id`，并要求工作流 Header 与业务 TraceId 一致。
- 增加可选 `jwt-local` 模式：校验 HS256 签名、过期时间、issuer、audience、token 类型与角色；默认请求头身份仅用于本地 Demo。
- 将安全 Agent Run 摘要持久化至 PostgreSQL，提供 `GET /api/tickets/{ticket_id}/runs`；摘要不保存 Prompt、原始 Evidence、推理链、认证头或密钥。
- 提供无模型 Key 的真实 PostgreSQL Mock Demo，便于复现“调查 → 审批 → 执行 → 审计”主链路。

## 当前可验证状态

最近一次完整 FlowPilot 回归为 **83 passed**，覆盖 PostgreSQL/Testcontainers、FastAPI ASGI 契约、LangGraph/SQLite checkpoint、MCP loopback、Mock Demo、TraceId、JWT-local 和 Agent Run 幂等摘要。

已完成的验证不等于生产声明：当前没有默认启用真实模型 provider、OpenTelemetry exporter、RS256/JWKS 联邦身份或 DG+SW 真实双进程联调，也没有性能 / 成本的生产基线。

| 能力 | 当前状态 |
|---|---|
| 确定性工单域、审批、执行、审计 | 已实现并经 PostgreSQL 回归验证 |
| LangGraph 单图、HITL checkpoint 恢复 | 已实现并验证 |
| MCP Streamable HTTP 调查客户端 | 已通过 loopback 协议回归验证 |
| Fake / deterministic 模型建议层 | 已实现；真实 provider 待接入 |
| JWT-local | 已实现；RS256/JWKS/OIDC 待补 |
| Agent Run 查询 | 已实现；前端 timeline / OTel spans 待补 |
| DG + SW 实时联调 | 待 SW 入站服务身份收口后再做 |

## 快速演示（不需要模型 API Key）

前置条件：Docker Desktop 和 `uv`。在仓库根目录启动 PostgreSQL：

```powershell
docker compose up -d --wait db
```

随后运行真实 FastAPI + PostgreSQL + LangGraph/SQLite 的 Mock 主场景：

```powershell
cd agents/python
$env:FLOWPILOT_DATABASE_URL = "postgresql://ecommerce:ecommerce_secret@127.0.0.1:5432/ecommerce_agents"
uv run python -m flowpilot.demo
```

预期输出包含：

- `ticket.status = "RESOLVED"`
- `proposal.action = "recover_expired_video_processing"`
- `execution.status = "succeeded"`
- `agent_run` 的稳定运行 ID、模型标签、步骤摘要与 TraceId

完整操作、边界和故障排查见 [Mock Demo Runbook](docs/DG-MOCK-DEMO-RUNBOOK.md)。Demo 使用 Fake Model、Mock SW Gateway 和 Mock Executor，不访问真实模型或 SW 服务。

## 架构与代码入口

```text
agents/python/flowpilot/
├── api/main.py                 # FastAPI API、TraceId、鉴权模式、工作流入口
├── agent_graph.py              # Triage / Investigation / Resolution / Risk Review 图
├── ticket_workflow.py          # 启动图、持久化 Evidence/Proposal/Agent Run
├── approval_workflow.py        # 审批落库、恢复 checkpoint、受控执行
├── domain/                     # 状态机、RBAC、动作合同、领域对象
├── db/repo.py                  # PostgreSQL 事务、行锁、幂等、审计、运行摘要
├── sw_video_ops_mcp_client.py  # MCP Streamable HTTP ClientSession
└── sw_video_recovery.py        # 受限 SW 恢复 HTTP adapter
```

- [运行时选型 ADR](docs/adr/ADR-001-agent-runtime.md)：MAF 与 LangGraph 同构 Spike 后的选型依据。
- [工作流 API Contract](docs/contracts/DG-FLOWPILOT-WORKFLOW-API.md)：运行时配置、身份模式、审批与 runs 查询契约。
- [Mock Demo Runbook](docs/DG-MOCK-DEMO-RUNBOOK.md)：无 Key 主场景复现步骤。
- [FlowPilot 测试](agents/python/tests/flowpilot/)：领域、数据库、API、MCP、工作流与安全边界的验证代码。

## 开发验证

```powershell
cd agents/python
uv run ruff check flowpilot tests/flowpilot
uv run ruff format --check flowpilot tests/flowpilot
uv run pytest tests/flowpilot -q
```

测试中的数据库路径使用 Testcontainers 的 PostgreSQL；本项目当前只将 FlowPilot 定向回归作为重构验收证据，不把遗留上游电商全仓测试当作 FlowPilot 的完成证明。

## 上游项目与致谢

本项目基于 Nitin Singh 的开源项目 [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) 进行授权重构与扩展。上游项目提供了多 Agent 电商平台、MAF/A2A、Docker、PostgreSQL、Redis 和 Next.js 等参考底座；我在此基础上完成了面向企业工单处置的领域建模、运行时选型、LangGraph 工作流、MCP 调查边界、审批与执行安全约束、测试和面试 Demo 重构。

感谢原作者的开源工作。保留的上游文件及其版权声明继续受原 [MIT License](LICENSE) 约束。

## License

This repository retains the upstream [MIT License](LICENSE). Copyright notices
and attribution for upstream material are preserved.
