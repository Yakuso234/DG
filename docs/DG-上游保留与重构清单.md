# DG / FlowPilot 上游保留与重构清单（Phase 0 交付物）

> - **审计日期**：2026-08-16
> - **审计范围**：本仓库当前 HEAD，提交 `341074c`（`fix(python): harden Windows encoding bootstrap`）
> - **上游来源**：`nitin27may/e-commerce-agents`（MIT），克隆基线提交 `b50827b`
> - **性质**：本清单是 **Phase 0 计划依据**。它只记录"保留/改造/替换/删除"的意图与理由，**不授权立即删除**。实际删除必须等 **ADR-001（MAF beta vs LangGraph 1.x + 官方 A2A/MCP SDK）完成后分批执行**，每批删除后须保证 `pytest`/Ruff/前端构建仍可跑。
> - **只读约束**：本次审计不修改除本文档外的任何文件，不运行会写文件或联网的命令。

---

## 0. 审计统计摘要（代码量）

| 目录 | 组成 | 大致规模 |
|---|---|---|
| `agents/python` | shared(42)、orchestrator(7)、auth_server(9)、5 个电商 specialists(各 5)、workflows(4)、evals(4)、config(prompts/workflows)、packages/mcp-{product,inventory}(10)、patch_maf.py、tests(55) + MCP 包测试(6) | **97 个业务 .py ≈ 12.7k 行** + 61 个测试文件 |
| `agents/dotnet` | Orchestrator、5 个电商 Agent、Mcp、Shared、Workflows + 12 个测试工程 | **112 个 .cs ≈ 17.0k 行** |
| `web` | `src/app`(32)、`src/components`(48，含 20+ 个 ui 原语)、`src/lib`(15)、`web/e2e`(39，多为电商截图) | **93 个 .tsx/.ts ≈ 13.1k 行** |
| `docker` | `init.sql`(34 张表)、Dockerfile ×2 | 34 张表 |
| `scripts` | dev.sh、seed.py、generate_embeddings.py、verify-setup.sh、visualize_workflows.py、migrate_tutorials_to_hugo.py | 7 个文件 |
| `docs` | 上游架构/API/安全/遥测等 18 篇 + images | 36 个文件 |
| `tutorials` | MAF v1 教程（Python + .NET 双实现，22 章） | **212 个文件** |
| `.claude` | plans/enhancements(13)、agents(6)、settings | 21 个文件 |
| `.github` | tests/build-images/evals 3 条 workflow | 3 个文件 |

**结论**：工程资产（shared、MCP 包骨架、JWT/身份、ContextVars、Prompt 组合、OTel、Compose/init.sql、前端 shell+SSE、evals 框架、dev.sh）集中在 `agents/python/shared`、`packages/mcp-*`、`web/src` 与根基础设施；电商业务代码集中在 5 个 specialists、`orchestrator/routes.py`（2480 行，42 个端点）、`shared/tools/*`、`workflows/*`、`scripts/seed.py`、`docker/postgres/init.sql` 与前端电商页面；`.NET` 与 `tutorials` 是纯上游演示产物。

---

## 1. 总表（模块 × 处置）

> 处置含义：**保留**=不改直接用；**改造保留**=保留骨架/机制，改业务域或接口；**替换**=整体重写但沿用其职责位置；**删除**=不再需要；**待定**=依赖 ADR-001 选型。
> 处置阶段对应路线图：P0=Phase 0（ADR 前）、P1=Phase 1（工单域）、P2=Phase 2（MCP）、P3=Phase 3（Agent 闭环）、P4=Phase 4（审批执行）、P5=Phase 5（评测）、P7=Phase 7（前端/文档）。

| # | 模块 | 现状 | FlowPilot 处置 | 理由（一句话） | 处置阶段 |
|---|---|---|---|---|---|
| 1 | `shared/db.py` | asyncpg 连接池 | **保留** | 框架无关的 DB 池，工单域直接复用 | P1 |
| 2 | `shared/config.py` | Pydantic Settings（287 行） | **改造保留** | 删电商开关、加 Ticket/RBAC/MCP 域配置，保留别名与密钥校验机制 | P1 |
| 3 | `shared/context.py` | ContextVars（身份/会话/steps/stream） | **改造保留** | 机制保留，角色枚举与新增 ContextVars（ticket_id 等）改为工单域 | P1 |
| 4 | `shared/auth.py` | JWT + X-Agent-Secret 双模中间件 | **改造保留** | 身份中间件通用；角色 `customer/seller/admin` → `submitter/handler/approver/admin/service` | P1 |
| 5 | `shared/jwt_utils.py`、`shared/oauth/*` | HS256/RS256、JWKS、服务令牌 | **改造保留** | 自托管 OAuth2/服务身份通用；audience/scope 从 `ecommerce-*` → `flowpilot-*` | P1 |
| 6 | `shared/middleware.py` | RunLogger/ToolAudit/PiiRedaction/中间件栈 | **保留** | 审计与 PII 掩码与业务域无关，直接复用（可扩展脱敏正则） | P1 |
| 7 | `shared/agent_observability.py` | StepRecorder → 时间线 | **待定** | 时间线采集概念必需；MAF `FunctionMiddleware` 实现待 ADR（LangGraph 用 astream_events 重建） | 待定 |
| 8 | `shared/agent_host.py` | A2A host（MAF-native 执行） | **待定** | A2A 服务骨架价值高；MAF 选型下保留、LangGraph 选型下用官方 A2A SDK 替换 | 待定 |
| 9 | `shared/remote_agent.py` | HandoffBuilder 远程客户端 | **待定** | 仅 MAF Handoff 需要；LangGraph 选型下删除 | 待定 |
| 10 | `shared/session.py`、`checkpoint_storage.py`、`factory.py`(后端) | MAF 会话/检查点后端 | **待定** | 持久化/恢复概念必需；MAF 保留、LangGraph 用官方 Postgres checkpointer 替换 | 待定 |
| 11 | `shared/prompt_loader.py` | YAML Prompt 组合（89 行） | **保留** | 框架无关，工单 Prompt 直接沿用该组合机制 | P3 |
| 12 | `shared/schema_context.py`、`tool_examples.py`、`tool_inputs.py` | 电商 Schema/工具示例注入 | **改造保留** | 机制保留，内容换成 Ticket/Evidence/ActionProposal 等 | P3 |
| 13 | `shared/context_providers.py` | 用户/订单/记忆上下文注入 | **改造保留** | 机制保留，改注入工单/证据/角色上下文 | P3 |
| 14 | `shared/guardrails/*` | 注入检测/输出净化/角色/脱敏 | **改造保留** | 安全护栏框架直接复用；`SANITIZE_TOOLS` 白名单与角色表换成工单域工具 | P5 |
| 15 | `shared/hitl.py` | HITL 审批中间件 + DB 助手 + 执行器 | **改造保留** | 审批队列/决议概念复用；`execute_approved_action` 硬编码电商 SQL → 由 action-executor 替换 | P4 |
| 16 | `shared/usage_db.py` | usage_logs / agent_execution_steps | **改造保留** | 轨迹持久化思路复用，表结构收敛到 `AgentRun`/`Execution` | P1/P3 |
| 17 | `shared/workflow_loader.py` | MAF 声明式工作流 | **待定** | 教学脚手架；MAF 保留、LangGraph 以 StateGraph 替换 | 待定 |
| 18 | `shared/tools/*`（8 个） | 电商工具（cart/inventory/loyalty/pricing/return/seller/user/memory） | **删除** | 全部电商域工具，与工单无关 | P1 |
| 19 | `orchestrator/` | 前端门面 FastAPI + 路由 Agent（2480 行路由） | **改造保留** | 保留 FastAPI 门面/SSE/会话/审批/审计端点骨架；删除电商端点；演化为 `flowpilot-api` | P1–P3 |
| 20 | `product_discovery/` | 商品发现 Agent | **删除** | 电商域，由 Investigation Agent（调用 ticket/knowledge MCP）替换 | P3 |
| 21 | `order_management/` | 订单 Agent | **删除** | 电商域，职责由工单状态机 + Resolution 替换 | P3 |
| 22 | `pricing_promotions/` | 定价促销 Agent | **删除** | 电商域，无对应工单职责 | P3 |
| 23 | `review_sentiment/` | 评论情感 Agent | **删除** | 电商域，风险语义由 Risk Reviewer 替换 | P3 |
| 24 | `inventory_fulfillment/` | 库存履约 Agent | **删除** | 电商域，业务状态查询由 mock-business MCP 替换 | P3 |
| 25 | `auth_server/` | 自托管 OAuth2 AS（9 文件） | **改造保留** | 服务身份/RBAC/RS256 机制通用；audience/scope 改名 | P1 |
| 26 | `workflows/`（pre_purchase/return_replace/group_chat） | 电商 MAF 工作流 | **删除**（运行时机）**待定**（运行时选型） | 业务域全电商；"workflow-runtime" 待 ADR 后重建 | P3/待定 |
| 27 | `config/prompts/` | 6 个电商 Prompt + `_shared/` | **改造保留** | 保留 `_shared/` 组合片断与组合规则，6 个电商 YAML 换成工单 Agent Prompt | P3 |
| 28 | `config/workflows/` | text-pipeline + SCHEMA.md | **待定/删除** | 教学样例，随 workflow-runtime 选型处置 | 待定 |
| 29 | `evals/` | 评测器 + CLI + 7 个电商数据集 | **改造保留** | evaluator/run_evals/safety 框架复用；电商数据集替换为工单/安全/越权/注入固定集 | P5 |
| 30 | `packages/mcp-product` | 商品 MCP（FastMCP + JWKS 验证器） | **改造保留** | MCP 服务骨架（Streamable HTTP/lifespan/健康检查/scope 验证）复用，重写为 `ticket-mcp`/`knowledge-mcp` | P2 |
| 31 | `packages/mcp-inventory` | 库存 MCP | **改造保留** | 同上，重写为 `mock-business-mcp`（确定性业务状态/故障注入） | P2 |
| 32 | `tests/`（55 文件） | 单元/集成测试 | **改造保留** | 基础设施测试（auth/guardrails/hitl/middleware/session/checkpoint/mcp-oauth）复用；电商域测试删除；新增工单域测试 | 各阶段 |
| 33 | `patch_maf.py` | MAF 打包补丁 | **待定** | 仅 MAF 需要；LangGraph 选型下删除 | 待定 |
| 34 | `pyproject.toml` | uv workspace + 依赖 | **改造保留** | 保留 uv workspace/ruff/pytest 配置；MAF 依赖随 ADR 增删 | P0 |
| 35 | `Dockerfile`、`Dockerfile.mcp` | 多目标镜像 / MCP 独立镜像 | **改造保留** | 多目标 `ARG AGENT_NAME` 与 MCP 精简镜像模式复用，Agent 名与依赖改工单域 | P1–P3 |
| 36 | `agents/dotnet/` | .NET 双实现（112 .cs） | **删除** | 明确要删的 .NET 双实现，与纯 Python 目标冲突 | P0 后（见 §5 批 1） |
| 37 | `web` 工程配置（package.json/tsconfig/eslint/vitest/playwright/tailwind/components.json） | Next.js 16 + React 19 + Tailwind 4 + shadcn/ui | **保留** | 前端工程设施与依赖全保留 | P7 |
| 38 | `web/src/app`（登录/聊天/管理/agents/runs 布局） | 认证布局 + 侧边栏 + SSE 聊天 | **改造保留** | shell/认证/SSE/审批/审计/用量页面复用，改工单工作台视觉 | P7 |
| 39 | `web/src/app`（电商页面：home/shop/cart/checkout/products/orders/profile/seller） | 电商页面 | **删除** | 电商页面与工单工作台无关 | P7 |
| 40 | `web/src/components/ui/*` | shadcn/ui 原语（20+） | **保留** | 通用 UI 原语直接复用 | P7 |
| 41 | `web/src/components/chat/*`、`sidebar`、`top-bar` 等 | 聊天渲染 + 布局组件 | **改造保留** | agent-timeline/rich-message/action-chips 复用；product/order/checkout/comparison/return 卡片换成工单/证据/审批卡片 | P7 |
| 42 | `web/src/lib`（api/auth-context/chat-schemas/format/nav/toast/utils/motion） | 前端基础设施 | **改造保留** | API 客户端/SSE/auth context/工具函数复用，端点与类型改工单域 | P7 |
| 43 | `web/src/lib`（cart-context/images/scenarios/agents） | 电商前端状态 | **删除** | 购物车上下文/商品图/电商 demo 场景/电商 Agent 目录 | P7 |
| 44 | `web/e2e/*` | Playwright 电商 E2E + 截图 | **删除**（重建） | 电商 spec 与截图删除；工单域 E2E 重建 | P7 |
| 45 | `docker-compose.yml` | db/redis/aspire + 6 Agent + MCP + 前端 | **改造保留** | infra（db/redis/aspire）与 profile 机制复用；Agent 服务名与 registry 改工单域 | P1–P3 |
| 46 | `docker-compose.dotnet.yml` | .NET 栈 compose | **删除** | 随 .NET 双实现删除 | P0 后（批 1） |
| 47 | `docker/postgres/init.sql` | 34 张表 | **改造保留**（表级拆分，见 §3.2） | 保留基础设施表；删 18 张电商表；新增工单域 7 表 | P1 |
| 48 | `scripts/dev.sh` | 一键编排（295 行） | **改造保留** | infra/seed/agents/frontend 编排逻辑复用；服务名与健康检查改工单域 | P1–P7 |
| 49 | `scripts/seed.py` | 电商确定性种子（942 行） | **替换** | 电商种子删除；重写工单域确定性种子（保留 `random.seed` 确定性思路） | P1 |
| 50 | `scripts/generate_embeddings.py` | 向量嵌入生成 | **改造保留** | knowledge-mcp 知识库嵌入沿用 | P2 |
| 51 | `scripts/verify-setup.sh` | 环境校验 | **改造保留** | 校验逻辑复用，版本/服务改工单域 | P0 |
| 52 | `scripts/visualize_workflows.py`、`migrate_tutorials_to_hugo.py` | 工作流可视化 / 教程迁移 | **待定 / 删除** | visualize 随 workflow-runtime 选型；migrate 教程工具随 tutorials 删除 | 待定/P0 |
| 53 | `docs/`（上游 18 篇） | 上游架构/API/安全文档 | **改造保留/删除** | 过渡期保留作参考；工单域重写 README/架构/安全/评测文档，删除纯电商 API 参考 | P7 |
| 54 | `tutorials/`（212 文件） | MAF 教程（Python+.NET） | **删除** | 教程与电商演示/教程发布耦合，纯演示产物 | P0 后（批 1） |
| 55 | `.claude/` | 上游 plans/enhancements(13)、agents(6) | **改造保留/删除** | 电商增强计划删除；通用子代理定义（reviewer/auditor 等）可留 | P0 后 |
| 56 | `.github/workflows/`（3 条） | CI（pytest/镜像/evals） | **改造保留** | 删 .NET job、改 Agent matrix 与 eval 数据集；保留 pytest 覆盖率门禁 | P0–P5 |
| 57 | 根 `README.md`/`CLAUDE.md`/`CONTRIBUTING.md`/`.env.example` | 上游电商说明 | **改造保留** | 重写为 FlowPilot；保留 MIT 归属与 `.env.example` 结构 | P7 |
| 58 | `LICENSE` | MIT | **保留** | 必须保留上游版权与 LICENSE | 始终 |

---

## 2. 分节详述

### 2.1 ① 直接保留并复用（不改业务语义）

以下资产与"电商"或"MAF"绑定最弱，是 FlowPilot 可直接继承的工程底座：

1. **`shared/db.py`** — asyncpg 池管理（`init_db_pool`/`get_pool`/`close_db_pool`），工单域照用。
2. **`shared/prompt_loader.py`** — YAML Prompt 组合器：base + `_shared/grounding-rules` + 角色指令 + schema 引用 + 工具示例。这是上游少数"框架无关、业务无关"的纯文本工程资产，Triage/Investigation/Resolution/Risk Reviewer 直接写新的 YAML 即可。
3. **`shared/context.py`** — ContextVars 机制本身（身份/会话/steps/stream 队列）是通用并发安全模式，保留；只是新增工单域 ContextVar 并改角色枚举。
4. **`shared/middleware.py`** — `AgentRunLogger`（run 计时 + correlation id）、`ToolAuditMiddleware`（工具调用审计）、`PiiRedactionMiddleware`（卡号/SSN 脱敏）。审计与脱敏概念与工单域完全通用，是 FlowPilot "可追溯、可审计"红线的基础设施。
5. **`shared/guardrails/`** 的安全机制（`injection_middleware`、`output_middleware`、`sanitize`）— 注入检测与存储型注入净化是 FlowPilot 评测红线的现成实现，仅需换 `SANITIZE_TOOLS` 白名单（现在列的是电商工具）与角色表。
6. **`packages/mcp-{product,inventory}` 的服务骨架**（非业务工具）— `FastMCP` + Streamable HTTP + `_lifespan` DB 池 + `host=0.0.0.0` 反 DNS-rebinding + 健康检查 + `auth.py::JwksTokenVerifier`（RS256 scope 验证）。这是"独立可发布 uv workspace 成员"的教科书结构，直接套给 ticket-mcp/knowledge-mcp/mock-business-mcp。
7. **`shared/telemetry.py`** — OTel SDK + OTLP + GenAI 语义约定 + httpx/asyncpg/FastAPI/logging 自动插桩 + Aspire 导出。FlowPilot 的 Trace ID 关联（HTTP/A2A/MCP/LLM/DB/审批）直接复用。
8. **前端 `web/src/components/ui/*`**（shadcn/ui 原语）+ 工程配置（Next.js 16/React 19/Tailwind 4/ESLint/Vitest/Playwright 配置）— 纯 UI 原语与构建设施，全部保留。
9. **`docker-compose.yml` 的 infra 段**（db/redis/aspire + 健康检查 + profile 机制）与 **`Dockerfile` 多目标模式**（`ARG AGENT_NAME`）、**`Dockerfile.mcp` 精简镜像模式** — 编排与镜像工程复用。
10. **`scripts/dev.sh` 的编排骨架** — `--clean/--seed-only/--infra-only` 标志、健康等待、stale volume 自愈逻辑，全部可保留（仅改服务名）。
11. **`LICENSE`** — MIT，必须保留。

### 2.2 ② 改造后保留（说明改什么）

按改造强度分三档：

**A. 只改命名/枚举/配置，机制不变**
- `shared/config.py`：删除 `RETURN_HITL_THRESHOLD`、`MCP_PRODUCT_*`/`MCP_INVENTORY_*` 等电商开关；新增 `TICKET_*`、`APPROVAL_*`、`EXECUTION_*`、RBAC 角色；保留 Pydantic Settings 的 env 别名机制与密钥强度校验。
- `shared/auth.py`：`_ALLOWED_ROLES` 从 `{customer, seller, admin, system}` → `{submitter, handler, approver, admin, service}`；`_identity_anomaly` 逻辑与双模（shared secret / service token）保持不变。
- `shared/jwt_utils.py` / `shared/oauth/*` / `auth_server/*`：audience 从 `ecommerce-*` → `flowpilot-*`，scope 从 `agent:invoke`/`mcp:product` → `agent:invoke`/`mcp:ticket`/`mcp:knowledge` 等；RS256 签名/JWKS/动态注册机制不动。
- `shared/context_providers.py`：`UserProfileProvider`/`RecentOrdersProvider`/`AgentMemoriesProvider` → `TicketProvider`/`EvidenceProvider`/`RoleContextProvider`，注入工单字段而非 `loyalty_tier/total_spend`。

**B. 保留机制，重写业务内容**
- `shared/schema_context.py` / `tool_examples.py` / `tool_inputs.py`：Schema 与工具示例内容从 products/orders/reviews 换成 Ticket/Evidence/ActionProposal/Approval/Execution 及 MCP 工具契约。
- `config/prompts/`：保留 `_shared/grounding-rules.yaml`、`schema-context.yaml`、`tool-examples.yaml` 的组合规则；删除 6 个电商 Prompt YAML，新增 `triage`/`investigation`/`resolution`/`risk-reviewer` YAML。
- `shared/usage_db.py`：`usage_logs`（Token/成本）与 `agent_execution_steps`（时间线）思路复用，字段收敛为 `AgentRun`/`Execution` 模型。
- `evals/`：`evaluator.py`（groundedness/correctness/completeness 打分 + 路由断言 + 时延/Token/成本汇总）、`run_evals.py`（CLI）、`safety_evaluator.py`（red-team）框架复用；7 个电商数据集全部替换为工单/越权/注入/部分失败固定集，并补 P50/P95 与单 Agent 基线对比。
- `packages/mcp-*`：MCP 服务骨架保留，`server.py` 里的 `@mcp.tool` 全换（商品搜索→工单查询/知识检索/业务状态查询），`auth.py` 的 audience/scope 换名，包名改为 `flowpilot-mcp-ticket`/`flowpilot-mcp-knowledge`/`flowpilot-mcp-mock-business`。
- `scripts/seed.py`：整体替换为工单域确定性种子（保留 `random.seed(42)` 可复现思路与 asyncpg 批量写入模式）。
- `web/src/lib/api.ts`/`auth-context.tsx`/`chat-schemas.ts`：SSE 流式聊天（`chatStream`）、JWT localStorage 持久化、API 单例模式复用，端点与消息 schema 换工单域。

**C. 保留骨架，职责替换（涉及业务入口）**
- `orchestrator/`：保留 `main.py`（FastAPI + CORS + lifespan + FK 异常映射）与 `routes.py` 中的认证（signup/login/refresh）、会话（conversations CRUD）、聊天（`/api/chat`、`/api/chat/stream`）、管理（admin/hitl/audit/usage/runs）端点骨架；删除 products/orders/cart/checkout/seller/marketplace 端点。`agent.py` 的 `call_specialist_agent` 工具（A2A 路由 + SSE 转发 + step 合并）改造为路由到 ticket Agent。
- `shared/hitl.py`：保留审批队列的 DB 助手（`list/get/resolve`）与"pending→approved/denied/executed"状态机思路；`execute_approved_action`（硬编码 cancel_order/process_refund 等电商 SQL）由独立 `action-executor` 服务替换（策略校验 + 幂等键 + 审计，不盲信 Agent 输出）。
- `docker/postgres/init.sql`：见 §3.2 表级拆分。
- `web/src/app/(app)/layout.tsx` + `chat` + `admin/{approvals,audit,usage}` + `agents` + `runs`：shell 与 SSE 聊天/审批/审计/用量/运行时间线页面复用，视觉与数据模型改工单工作台；`components/chat/agent-timeline.tsx`、`rich-message.tsx` 改造为渲染证据引用/审批卡。
- `.github/workflows/`：`tests.yml` 删 dotnet job 与电商 agent matrix；`evals.yml` 换数据集与服务；`build-images.yml` matrix 换工单 Agent。
- 根文档 `README.md`/`CLAUDE.md`/`CONTRIBUTING.md`/`.env.example`：重写为 FlowPilot，明确"参考上游 A2A/MCP 工程结构，业务域与协作逻辑由 DG 重构"与 MIT 归属。

### 2.3 ③ 删除清单（含数据库表与前端页面）

#### 2.3.1 电商业务代码（Python）
- `product_discovery/`、`order_management/`、`pricing_promotions/`、`review_sentiment/`、`inventory_fulfillment/`（各 5 文件：agent/tools/prompts/main/`__init__`）。
- `shared/tools/`：`cart_tools.py`、`inventory_tools.py`、`loyalty_tools.py`、`pricing_tools.py`、`return_tools.py`、`seller_tools.py`、`user_tools.py`（`memory_tools.py` 与长期记忆一起按 P2 裁撤）。
- `workflows/pre_purchase.py`、`workflows/return_replace.py`（电商工作流；`group_chat.py` 为 MAF 编排演示，随 ADR 处置）。
- `orchestrator/routes.py` 中电商端点：`/api/products*`、`/api/orders*`（含 cancel/return）、`/api/returns/*`、`/api/cart*`、`/api/checkout`、`/api/profile`（电商画像部分）、`/api/seller/*`、`/api/marketplace/*`。
- `config/prompts/{product-discovery,order-management,pricing-promotions,review-sentiment,inventory-fulfillment}.yaml`。
- `evals/datasets/{product_discovery,order_management,pricing_promotions,review_sentiment,inventory_fulfillment}.json`（`orchestrator_routing.json` 与 `red_team.json` 内容按工单域重写，文件可留可重建）。
- `scripts/seed.py`（电商种子）、`scripts/migrate_tutorials_to_hugo.py`（教程发布工具）。

#### 2.3.2 数据库表（`docker/postgres/init.sql`）
**删除 18 张电商表**：
`products`、`product_embeddings`、`price_history`、`orders`、`order_items`、`order_status_history`、`returns`、`carts`、`cart_items`、`reviews`、`warehouses`、`warehouse_inventory`、`carriers`、`shipping_rates`、`restock_schedule`、`coupons`、`promotions`、`loyalty_tiers`。

**市场层待定/删除 3 张**（P2 动态 Agent 发现可裁）：
`agent_catalog`、`access_requests`、`agent_permissions` —— 若保留则改造成工单 Agent 注册表，否则删除。

**保留并改造 13 张**：
- 身份：`users`（字段改 RBAC 角色）、`oauth_clients`、`oauth_signing_keys`、`oauth_tokens`（auth-server 用）。
- 会话/轨迹：`conversations`、`messages`、`usage_logs`、`agent_execution_steps`（→ `AgentRun`）。
- 审批：`tool_approval_requests`、`hitl_requests`（合并为 `Approval` 一张，保留 `approved_by`/`admin_note`/`execution_result`/`resolved_at` 版本语义）。
- `agent_memories`（长期记忆，P2 裁撤候选）；`workflow_checkpoints`（随 ADR：MAF 保留 / LangGraph 用官方 checkpointer 重建）。

**新增 7 张工单域表**：`tickets`、`evidence`、`action_proposals`、`approvals`、`executions`、`agent_runs`（或复用 agent_execution_steps 演化）、`eval_cases`/`eval_results`。

#### 2.3.3 .NET 双实现
- 整个 `agents/dotnet/`（112 个 .cs、17 个工程、12 个测试工程）、`docker-compose.dotnet.yml`、`scripts/dev.sh` 的 `--dotnet` 分支、`tests.yml` 的 `dotnet-tests` job。

#### 2.3.4 前端页面与组件（`web/src`）
**删除页面**：
- 公共商城：`app/shop/**`（layout/page/products/products/[id]/assistant）。
- 认证内电商页：`app/(app)/home`、`cart`、`checkout`、`products`、`products/[id]`、`orders`、`orders/[id]`、`profile`、`seller`、`seller/products`。
- `app/page.tsx` 与 `components/landing/` 的电商落地页（改为工单工作台入口）。

**删除组件**：`components/shop/*`、`components/demo/*`、`components/landing/*`、`components/agents/`（电商 Agent 目录展示）、`components/chat/{product-card,order-card,comparison-card,checkout-card,return-card}.tsx`、`components/star-rating.tsx`（商品评分）。

**删除 lib**：`lib/cart-context.tsx`、`lib/images.ts`（商品图）、`lib/scenarios.ts`（电商 demo 场景）、`lib/agents.ts`（电商 Agent 目录）。

**删除 E2E**：`web/e2e/` 全部电商 spec 与截图（`chat-shopping`、`shopping-flow`、`ui-features`、`readme-screenshots` 及 30+ PNG）；重建工单域 spec。

#### 2.3.5 教程与上游文档
- `tutorials/`（212 文件）整体删除（MAF 教程，Python+.NET 双实现，含 21-capstone-tour 等与电商演示强耦合）。
- 上游 `docs/` 中纯电商 API 参考（`api-reference.md`、`database-schema.md` 的电商段）随工单域重写；`docs/images/`（架构图）重绘。

### 2.4 ④ 待 ADR-001 定夺（MAF beta vs LangGraph 1.x + 官方 A2A/MCP SDK）

以下模块的"机制"FlowPilot 都需要，但"具体实现"依赖运行时选型，**在 ADR 完成前不删、不重写**：

| 模块 | 选 MAF beta 处置 | 选 LangGraph 1.x 处置 |
|---|---|---|
| `shared/agent_host.py`（A2A 服务骨架） | 保留（`agent.run` 原生执行 + SSE） | 替换为 LangGraph 节点 + 官方 A2A SDK `A2AServer` |
| `shared/remote_agent.py`（Handoff 远程客户端） | 保留（HandoffBuilder 用） | 删除 |
| `shared/session.py` + `factory.get_session_storage` | 保留（MAF AgentSession 后端） | 替换为 LangGraph `langgraph-checkpoint-postgres` |
| `shared/checkpoint_storage.py` + `factory.get_checkpoint_storage` | 保留（PostgresCheckpointStorage） | 替换为官方 Postgres checkpointer（`workflow_checkpoints` 表重定义） |
| `shared/workflow_loader.py` + `config/workflows/` | 保留（MAF 声明式工作流） | 替换为 LangGraph `StateGraph`/`create_react_agent` |
| `shared/agent_observability.py`（StepRecorder 中间件） | 保留（MAF `FunctionMiddleware`） | 用 LangGraph 的 `astream_events`/callbacks 重建等价时间线 |
| `shared/hitl.py` 的 `HITLFunctionMiddleware` | 保留（MAF `FunctionMiddleware`） | 用 LangGraph `interrupt()` 实现持久化挂起（DB 助手部分保留） |
| `shared/middleware.py` 中间件栈 | 保留（MAF Agent/Chat/Function 中间件） | 改写为 LangGraph 的 node/前置后置钩子（审计/脱敏逻辑保留） |
| `evals/evaluator.py` 的 agent 执行接口 | 保留（`agent.run`） | 改为 `graph.invoke`/`graph.astream`（打分逻辑保留） |
| `agents/python/patch_maf.py` | 保留（MAF 打包补丁） | 删除 |
| `pyproject.toml` 的 `agent-framework*` 依赖 | 保留 | 替换为 `langgraph`/`langgraph-checkpoint-postgres`/官方 A2A/MCP SDK |
| specialists 的 `agent.py`/`prompts.py` `@tool` 模式 | 保留并改名（triage/investigation/resolution/risk-reviewer） | 用 LangGraph 节点 + 结构化输出重写（Prompt YAML 复用） |
| `Dockerfile` 的 MAF bootstrap | 保留 | 去掉 MAF 启动步骤 |

**两套选型都保留（框架无关）**：`shared/db.py`、`shared/config.py`、`shared/context.py`、`shared/auth.py`、`shared/jwt_utils.py` + `oauth/*`、`shared/prompt_loader.py`、`shared/guardrails`（regex/sanitize 部分）、`shared/telemetry.py`、`auth_server/`、`packages/mcp-*` 骨架、`docker-compose` infra、前端 shell/SSE、`scripts/dev.sh`。

> 建议：Phase 0 的 Spike A/B 正应验证上表两列在"结构化状态 + MCP 读工具 + 持久化中断/恢复 + Fake Model 测试 + A2A 边界"上的等价性，ADR-001 依据实测数据，而非"LangGraph 更新"。

### 2.5 ⑤ 电商域删除顺序建议（分批，先业务代码后基础设施，每批后可测）

> 前提：ADR-001 落地并记录回退路径后开始；每批完成后跑 `cd agents/python && uv run pytest`、`uv run ruff check .`，并记录基线。

- **批 1（纯删除，零依赖业务）**：`agents/dotnet/`、`docker-compose.dotnet.yml`、`tutorials/`、`scripts/migrate_tutorials_to_hugo.py`、`tests.yml` 的 dotnet job。影响面小，不触碰 Python 业务，可先行。
- **批 2（电商 Agent 与工具，先停引用再删）**：删除 5 个电商 specialists、`shared/tools/*`、`workflows/pre_purchase.py`+`return_replace.py`、`config/prompts/` 6 个电商 YAML、`evals/datasets/` 电商 JSON；同步删/改引用它们的测试（`test_shared_tools`、`test_pre_purchase_workflow`、`test_return_replace_workflow`、`test_eval_*`、`test_handoff_orchestration` 等，见 §4）。此批后 `orchestrator` 会因 import 断裂，故与批 3 配合。
- **批 3（orchestrator 收敛 + 建工单域骨架）**：删 `routes.py` 电商端点与 `context_providers.py`/`schema_context.py`/`tool_examples.py` 的电商内容；落地 `tickets/evidence/action_proposals/approvals/executions/agent_runs` 表与状态机（Phase 1）。此批是"删除"与"重建"的交接点，工单域闭环（无 LLM）测试通过后再进下一批。
- **批 4（基础设施表 + 种子 + MCP 包重写）**：删 `init.sql` 18 张电商表，重写 `scripts/seed.py`，重写 `packages/mcp-*` 为 ticket/knowledge/mock-business（Phase 2）。MCP 契约测试通过后再动 Agent。
- **批 5（前端 + 文档收尾）**：删 `web` 电商页面/组件/lib/e2e，重建工单工作台（Phase 7）；重写 README/CLAUDE/CONTRIBUTING/架构图，确保 Demo Runbook 可跑。

---

## 3. 审计发现的依赖关系备注

以下"删除项"被现有代码/测试/CI 引用，删除时须同步处理，否则 `pytest` 收集或导入会失败：

1. **`orchestrator/routes.py`（2480 行）** 是被 `web` 前端与几乎所有集成测试依赖的超级入口：`/api/chat`、`/api/chat/stream` 依赖 `orchestrator.agent.create_orchestrator_agent` → 依赖 5 个 specialists 的 `AGENT_REGISTRY`；`/api/products|orders|cart|checkout|seller|marketplace` 依赖电商表。删电商端点须与批 2/批 3 同步，否则前端电商页与 `test_orchestrator_routes_unit.py` 断裂。
2. **`shared/tools/*`** 被 `test_shared_tools.py`、`test_destructive_tool_gates.py`、`test_tool_input_validation.py`、`test_tool_role_guards.py`、`test_clamp_limit.py` 直接引用。
3. **`workflows/{pre_purchase,return_replace,group_chat}.py`** 被 `test_pre_purchase_workflow.py`、`test_return_replace_workflow.py`、`test_workflow_group_chat.py`、`test_workflow_loader.py`、`test_visualize_workflows.py` 引用。
4. **`evals/datasets/*.json`** 被 `test_eval_datasets.py`、`test_eval_routing.py`、`test_eval_safety.py` 与 `evals/run_evals.py`（`AGENT_FACTORIES` 表硬编码 5 个电商 Agent 名）引用；`evals.yml` 的循环也硬编码 `product-discovery … inventory-fulfillment`。
5. **`config/prompts/*.yaml`** 被 `test_prompt_loader.py` 与每个 agent 的 `prompts.py` 引用；`config/workflows/text-pipeline.yaml` 被 `test_workflow_loader.py` 引用。
6. **`docker/postgres/init.sql` 电商表** 被 `scripts/seed.py`（全量写入）、`agents/python/tests/conftest.py`（testcontainers 建表）、5 个电商 specialists 的 `tools.py`、`orchestrator/routes.py` 电商端点、`shared/hitl.py`（orders/returns SQL）、`shared/tools/*`、`shared/context_providers.py`（users/agent_memories）引用。
7. **`.github/workflows/`**：`tests.yml` 引用 `agents/dotnet` 与 `--all-packages`（含 mcp 包）；`build-images.yml` matrix 硬编码 6 个电商 Agent；`evals.yml` 循环硬编码电商 Agent 与数据集。删电商后三条 workflow 均需同步更新。
8. **`web`**：`web/src/lib/api.ts` 指向电商端点；`components/chat/*` 渲染 product/order 卡片依赖 `chat-schemas.ts` 的电商消息类型；`web/e2e` 依赖电商页面与 `NEXT_PUBLIC_API_URL`。前端删除须与批 5 重写同步，否则 build/typecheck 失败。
9. **`shared/config.py` 的 `AGENT_REGISTRY`/`MCP_*`/`RETURN_HITL_THRESHOLD`** 等电商配置项被 `docker-compose.yml`、`orchestrator/agent.py`、`shared/hitl.py`、`packages/mcp-*` 与 `test_env_aliases.py`/`test_config_loader.py` 引用；改造 config 时这些引用须同步改。
10. **MAF 专属代码**（`agent_host.py`、`session.py`、`checkpoint_storage.py`、`workflow_loader.py`、`remote_agent.py`、`patch_maf.py`、`agent_observability.py`、`hitl.py` 中间件）均从 `agent_framework._*` 子模块 import（绕开空 `__init__`）。若 ADR 选 LangGraph，这些文件删除/替换后，`pyproject.toml` 的 `[tool.hatch.build.targets.wheel].packages` 与 `[tool.coverage.run].source` 里的电商包名也要同步。
