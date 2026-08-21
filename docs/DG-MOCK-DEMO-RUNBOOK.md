# DG / FlowPilot Mock 主场景演示手册

> 目标：不需要 Qwen、OpenAI 或 SW 服务，在真实 PostgreSQL 上演示一次
> “调查 → 提案 → 人工审批 → 受控执行 → 审计”的完整 API 主链路。

## 演示边界

- 使用真实 FastAPI、asyncpg/PostgreSQL、LangGraph、SQLite checkpoint 与领域审计。
- 使用 `MockSwVideoOpsGateway`、`MockBusinessActionRunner` 与 Fake Model；不会访问 SW、MCP 网络端点或任何模型 API。
- 默认使用 `FLOWPILOT_AUTH_MODE=headers` 的本地 Demo 身份头；不把它当作 JWT 演示或生产鉴权证据。
- 这证明 DG 的本地持久化闭环，不应表述为 DG+SW 双项目联调或真实 LLM 效果。

## 前置条件

- Docker Desktop 已启动。
- 已安装 `uv`，仓库 Python 环境已可执行 `uv run`。

在仓库根目录启动 PostgreSQL：

```powershell
docker compose up -d --wait db
docker compose ps db
```

第二条命令应显示 `healthy`。不要在 `health: starting` 时继续：首次启动的
PostgreSQL 正在执行完整上游 Schema，过早运行 Demo 会与它发生建表竞争。演示命令只会幂等应用 `init.sql` 中的 FlowPilot 域 Schema，因此旧本地卷也可使用，不会重复执行上游电商建表语句。

## 一键运行

```powershell
cd agents/python
$env:FLOWPILOT_DATABASE_URL = "postgresql://ecommerce:ecommerce_secret@127.0.0.1:5432/ecommerce_agents"
uv run python -m flowpilot.demo
```

命令输出 JSON。应关注：

- `ticket.status = "RESOLVED"`
- `proposal.action = "recover_expired_video_processing"`
- `execution.status = "succeeded"`
- `graph_steps_before_approval` 不含 `approval`，`graph_steps_after_approval` 才出现它
- `mock_business_operations` 只有一条 `restart_pipeline`，用于说明受控执行已发生；其 `entity_id=901` 是 Mock 业务实体，工单 UUID/creator/video/trace 的权威执行范围仍在 `proposal.params`。

可替换 TraceId 方便演示时检索：

```powershell
uv run python -m flowpilot.demo --trace-id trace-interview-001
```

Demo 会将该值同时写入工作流请求头 `X-Trace-Id` 与请求体 `trace_id`；API
会在每个响应中回传同一个 Header。两者不一致时工作流会拒绝请求，避免一次
调查链路被拆成两个无法关联的 Trace。

## 面试演示顺序

1. 说明输入是租约过期的 PROCESSING 视频任务，Mock 仅替代外部 SW，不替代数据库或工作流。
2. 展示审批前步骤：`triage → investigation → resolution → risk_review`；此时没有写操作。
3. 展示 `ActionProposal` 的固定参数和 high risk，强调参数来自 Evidence 而非模型。
4. 展示批准后的 `execution.succeeded`、工单 `RESOLVED` 和 Mock 操作日志。
5. 说明生产化差异：将 Mock gateway/runner 替换为只读 MCP 与受控 SW HTTP adapter，模型仍只提供建议。

## 清理与故障排查

- 演示会在数据库中留下工单、Evidence、提案、审批、执行和审计记录，便于复盘；不要在共享数据库使用。
- 如需清空本地开发数据，明确确认后运行 `docker compose down -v`，它会删除本项目 Docker 卷。
- `connection refused`：确认 Docker Desktop 与 `docker compose ps db`。
- Schema 权限/初始化错误：检查连接串为本地 Compose 的 `ecommerce` 用户，并移除 `--skip-schema-init`。
- 此 Runbook 没有 API Key 依赖；等接入受控真实模型 provider 时，才需要配置你提供的 Qwen 或兼容 Key。
