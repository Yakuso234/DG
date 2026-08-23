# DG / FlowPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Workflow-LangGraph-1f2937.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2016-336791.svg)](https://www.postgresql.org/)

DG / FlowPilot 是一个面向企业故障处置的 Python 多 Agent 控制平面，也是我秋招后端 / Python Agent 应用开发岗位重构的个人项目。它把 Agent 置于明确的业务与安全边界中：Agent 负责调查和提出结构化建议；状态机、RBAC、动作合同、审批和幂等由确定性服务端代码负责。

第一条闭环围绕“短视频处理任务卡住”：创建工单 → 调查外部状态 → 生成恢复提案 → 风险复核 → 人工审批 → 受控执行 → 审计与运行轨迹查询。

> 这是对上游开源项目的授权重构与扩展，不是对其电商功能的简单复述。电商 Agent 与 MCP 存量已从当前工作树清理；如需查阅上游实现，可通过 Git 历史恢复，不能视为 FlowPilot 的已完成能力。

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
- 实现受限 `recover_expired_video_processing` 动作合同：固定业务范围、服务身份、TraceId、幂等键和严格响应校验；私有 SW HTTP 客户端禁用环境代理，避免本地/内网地址被代理重定向。

### 4. 补齐可观测、身份与演示能力

- API 统一生成或透传 `X-Trace-Id`，并要求工作流 Header 与业务 TraceId 一致。
- 增加可选 `jwt-local` 模式：校验 HS256 签名、过期时间、issuer、audience、token 类型与角色；默认请求头身份仅用于本地 Demo。
- 将安全 Agent Run 摘要持久化至 PostgreSQL，提供 `GET /api/tickets/{ticket_id}/runs`；真实 Provider 记录输入/输出 Token 与模型调用耗时，摘要不保存 Prompt、原始 Evidence、推理链、认证头或密钥。
- 提供无模型 Key 的真实 PostgreSQL Mock Demo，便于复现“调查 → 审批 → 执行 → 审计”主链路。
- 新增独立 `/flowpilot` 工作台：直接读取 FlowPilot API 的工单、Evidence、Proposal、Agent Run 与 Audit；审批恢复只在安全运行摘要能定位相同 `thread_id` 时才可操作，避免 UI 错绑 checkpoint。

## 当前可验证状态

最近一次完整 FlowPilot 回归为 **97 passed**，覆盖 PostgreSQL/Testcontainers、FastAPI ASGI 契约、LangGraph/SQLite checkpoint、MCP loopback、Mock Demo、Qwen 用量聚合、OpenTelemetry 安全 span、TraceId、JWT-local、CORS、Agent Run 幂等摘要，以及动作目录审批/RBAC 安全合同。

真实 Qwen-plus 在扩展后的 30 条固定评测集上顺序运行 3 轮：**90/90 通过、126 次模型调用、32,429 Token**；端到端 P50/P95 为 **3.315s / 6.476s**，Provider 调用 P50/P95 为 **3.309s / 6.469s**。该数据集覆盖合法恢复、状态/租约拒绝和注入文本，属于受控系统评测，不代表开放域准确率或生产 SLA。

已完成的验证不等于生产声明：Qwen Provider 已完成真实 Key 多轮受控评测，OTLP 已向本地 Aspire 成功导出，DG 已完成一次真实 SW 双进程恢复闭环；但仍没有生产采样/告警、RS256/JWKS 联邦身份或性能 / 成本的生产基线。

| 能力 | 当前状态 |
|---|---|
| 确定性工单域、审批、执行、审计 | 已实现并经 PostgreSQL 回归验证 |
| LangGraph 单图、HITL checkpoint 恢复 | 已实现并验证 |
| MCP Streamable HTTP 调查客户端 | 已通过 loopback 协议回归验证 |
| Fake / deterministic / Qwen 模型建议层 | Qwen Provider、30 条 × 3 轮真实 Key 评测和 Token/延迟采集已验证 |
| JWT-local | 已实现；RS256/JWKS/OIDC 待补 |
| Agent Run / Proposal 查询、OTel 与最小工作台 | 已实现本地观测与 `/flowpilot` 真实只读展示；生产身份、完整前端审批 E2E 与采样告警待补 |
| DG + SW 实时联调 | 已完成 1 次隔离过期 lease 的真实闭环：调查、HITL 审批、恢复、审计与重复执行幂等回归；SW 入站服务身份校验仍待补 |

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

## Qwen Plus 接入与 Python 后端启动

不要把 API Key 写入 `.env.example`、源码或 Git。PowerShell 当前窗口中设置：

```powershell
cd agents/python
$env:FLOWPILOT_STRUCTURED_MODEL = "qwen"
$env:DASHSCOPE_API_KEY = "你的 DashScope API Key"
$env:FLOWPILOT_QWEN_MODEL = "qwen-plus"
```

先运行不依赖 Docker / 数据库的两次调用冒烟测试：

```powershell
uv run python -m flowpilot.qwen_smoke
```

成功后，启动 PostgreSQL 并运行“真实 Qwen + Mock SW + Mock 执行器”的完整审批闭环：

```powershell
cd ../..
docker compose up -d --wait db
cd agents/python
$env:FLOWPILOT_DATABASE_URL = "postgresql://ecommerce:ecommerce_secret@127.0.0.1:5432/ecommerce_agents"
uv run python -m flowpilot.demo --structured-model-from-env
```

运行 7 场景真实模型评测（共 10 次模型调用：7 次分诊、3 次处置）：

```powershell
uv run python -m flowpilot.evaluation `
  --dataset evals/datasets/flowpilot_video_ops.json `
  --structured-model-from-env
```

评测输出分别给出整图延迟、模型调用延迟和输入/输出 Token；成本需要结合实际账户价格计算，项目不会硬编码可能变化的价格。

## OpenTelemetry 本地观测

FlowPilot 提供默认关闭的 OTel 接入：FastAPI、asyncpg、OpenAI/httpx 自动 instrumentation，以及工作流、四个逻辑 Agent、模型调用、审批恢复和受控执行自定义 span。遥测只记录稳定业务 ID、模型名、Token 和 latency，不记录 Prompt、rationale 或 Evidence 正文。

本地 Aspire 启动、环境变量和 span 层级见 [FlowPilot OTel Runbook](docs/DG-OTEL-RUNBOOK.md)。

## FlowPilot 最小工作台

`web/src/app/flowpilot/` 是与上游商城 `(app)` 壳隔离的独立路由，不复用电商登录或数据模型。它只读展示 FlowPilot 的工单、Evidence、Proposal、Agent Run 和 Audit；对于仍处于 `proposed` 的提案，页面只有在 Agent Run 安全摘要保存了同一提案的 `thread_id` 时才会调用既有的审批恢复 API。

本地启动、CORS 配置与边界见 [FlowPilot Workbench Runbook](docs/DG-FLOWPILOT-WORKBENCH-RUNBOOK.md)。Header 身份仅是本机 Demo 边界，不能作为生产认证方案。

单独启动 FastAPI（工作流默认关闭，只提供工单域 API）：

```powershell
uv run uvicorn flowpilot.api.main:app --host 127.0.0.1 --port 8090 --reload
```

浏览 `http://127.0.0.1:8090/docs` 或请求 `http://127.0.0.1:8090/health`。若要让模块级 FastAPI 同时启用完整工作流，还必须配置 `FLOWPILOT_WORKFLOW_ENABLED=true`、checkpoint 路径及 SW HTTP/MCP 网关；初次验证 Qwen 建议使用上面的完整 Mock 演示，避免把模型问题与 SW 联调问题混在一起。

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
web/src/app/flowpilot/           # 独立 FlowPilot 工作台（不复用商城 App Shell）
```

- [运行时选型 ADR](docs/adr/ADR-001-agent-runtime.md)：MAF 与 LangGraph 同构 Spike 后的选型依据。
- [工作流 API Contract](docs/contracts/DG-FLOWPILOT-WORKFLOW-API.md)：运行时配置、身份模式、审批与 runs 查询契约。
- [Mock Demo Runbook](docs/DG-MOCK-DEMO-RUNBOOK.md)：无 Key 主场景复现步骤。
- [FlowPilot Workbench Runbook](docs/DG-FLOWPILOT-WORKBENCH-RUNBOOK.md)：独立工作台本地展示与安全边界。
- [FlowPilot 测试](agents/python/tests/flowpilot/)：领域、数据库、API、MCP、工作流与安全边界的验证代码。

## 开发验证

```powershell
cd agents/python
uv run ruff check flowpilot tests/flowpilot
uv run ruff format --check flowpilot tests/flowpilot
uv run pytest tests/flowpilot -q
```

测试中的数据库路径使用 Testcontainers 的 PostgreSQL；`agents/python` 的默认 pytest 入口只收集 FlowPilot 定向回归，避免将已删除的电商模块误算为当前产品能力。

前端工作台验证：

```powershell
cd web
pnpm exec tsc --noEmit
pnpm lint
pnpm test
pnpm build
```

现有上游商城前端尚未纳入 FlowPilot 运行主线；独立工作台文件不新增 warning，构建、TypeScript 与 Vitest 是本次前端验收证据。

## 上游项目与致谢

本项目基于 Nitin Singh 的开源项目 [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) 进行授权重构与扩展。上游项目提供了多 Agent 电商平台、MAF/A2A、Docker、PostgreSQL、Redis 和 Next.js 等参考底座；我在此基础上完成了面向企业工单处置的领域建模、运行时选型、LangGraph 工作流、MCP 调查边界、审批与执行安全约束、测试和面试 Demo 重构。

感谢原作者的开源工作。保留的上游文件及其版权声明继续受原 [MIT License](LICENSE) 约束。

## License

This repository retains the upstream [MIT License](LICENSE). Copyright notices
and attribution for upstream material are preserved.
