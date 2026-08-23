# FlowPilot 最小工作台

`/flowpilot` 是与上游商城页面隔离的本地运维工作台。它展示 FlowPilot
持久化的工单、Evidence、Proposal、Agent Run 与审计事件；页面不构造
Demo Data，也不显示 Prompt、模型推理正文或 API Key。

## 1. 前置条件

- PostgreSQL 已运行，且已有 FlowPilot 数据。可先运行
  `python -m flowpilot.demo` 生成一条完整的 Mock 闭环记录。
- 已安装 `uv` 与 `pnpm`，并在 `web/` 执行过 `pnpm install --frozen-lockfile`。

## 2. 启动 API 与工作台

在第一个 PowerShell 窗口：

```powershell
cd agents/python
$env:FLOWPILOT_DATABASE_URL = "postgresql://ecommerce:ecommerce_secret@127.0.0.1:5432/ecommerce_agents"
$env:FLOWPILOT_CORS_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"
uv run uvicorn flowpilot.api.main:app --host 127.0.0.1 --port 8090 --reload
```

在第二个 PowerShell 窗口：

```powershell
cd web
$env:NEXT_PUBLIC_FLOWPILOT_API_URL = "http://127.0.0.1:8090"
pnpm dev --hostname 127.0.0.1
```

浏览 <http://127.0.0.1:3000/flowpilot>。

## 3. 可验证内容

选择一条已完成的 Mock 或 Qwen Demo 工单，应能看到：

- 工单状态、优先级、提交人和版本；
- 调查 Evidence 的工具名、来源和受限结构化数据；
- Proposal 的动作、参数、风险与当前持久化状态；
- Agent Run 的模型标签、Token（若 Provider 返回）、整图耗时、TraceId 与安全摘要；
- 审计事件的动作、角色、时间及可展开的 before/after 快照。

页面所有读取都走 FlowPilot API，而不是读取 Demo CLI 输出或浏览器缓存。

## 4. 审批恢复边界

新工作流会把 `thread_id` 与 `proposal_id` 一起写进 `AgentRun.output`。只有
`proposal.status=proposed` 且该匹配存在时，工作台才显示批准/拒绝按钮，并调用
`POST /api/workflows/proposals/{proposal_id}/approvals`。

旧历史运行没有 `thread_id` 时，页面明确禁用审批操作；绝不能根据 ticket ID、
提案 ID 或前端猜测生成 thread ID。模块级 API 要真正恢复审批，还需按 API
Contract 配置 `FLOWPILOT_WORKFLOW_ENABLED`、共享 checkpoint 和调查 Gateway。

本机页面用 `x-user-id/x-user-role=admin` 读取，这是 `headers` Demo 模式，不能
部署为真实认证。生产环境应使用 `jwt-local` 或后续 RS256/JWKS 身份边界。

## 5. 验证命令

```powershell
cd web
pnpm exec tsc --noEmit
pnpm lint
pnpm test
pnpm build
```

`pnpm lint` 会报告上游商城遗留 warning；本工作台新增文件不引入 ESLint error，
构建、TypeScript 和 Vitest 结果才是本阶段前端的验收依据。
