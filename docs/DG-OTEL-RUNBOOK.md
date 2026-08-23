# FlowPilot OpenTelemetry 本地验证

本 Runbook 验证 FlowPilot API、逻辑 Agent 节点、Qwen 调用、审批恢复和受控执行的 span。默认 `OTEL_ENABLED=false`；没有 Collector 时业务代码仍可运行。

## 1. 启动基础设施

在仓库根目录先启动 Aspire：

```powershell
docker compose up -d --wait aspire
```

FlowPilot 仍需要 PostgreSQL。如果本机尚未运行项目数据库，并且 `5432` 端口空闲，再执行：

```powershell
docker compose up -d --wait db
```

若 `5432` 已被现有 PostgreSQL 占用，直接复用该实例并确认 `FLOWPILOT_DATABASE_URL` 指向它，不要重复启动 Compose `db`。

本机 Aspire Dashboard：<http://127.0.0.1:18888>；OTLP gRPC 接收端口映射为 `18890`。

## 2. 启动 FlowPilot API

```powershell
cd agents/python
$env:FLOWPILOT_DATABASE_URL = "postgresql://ecommerce:ecommerce_secret@127.0.0.1:5432/ecommerce_agents"
$env:OTEL_ENABLED = "true"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:18890"
$env:OTEL_SERVICE_NAME = "flowpilot-api"
$env:GENAI_CAPTURE_CONTENT = "false"
uv run uvicorn flowpilot.api.main:app --host 127.0.0.1 --port 8090
```

保持窗口运行，再通过 Swagger 或 HTTP 客户端调用 API。`GENAI_CAPTURE_CONTENT=false` 是 FlowPilot 的默认安全选择，避免 Prompt、模型正文或原始 Evidence 进入遥测后端。

## 3. 观察 span

在 Aspire 的 Traces 页面按 `service.name=flowpilot-api` 过滤。完整 Agent 路径可出现：

```text
HTTP POST /api/workflows/tickets/{id}/start
└── flowpilot.workflow.start
    ├── flowpilot.agent.triage
    │   └── flowpilot.model.call
    ├── flowpilot.agent.investigation
    ├── flowpilot.agent.resolution
    │   └── flowpilot.model.call
    └── flowpilot.agent.risk_review

HTTP POST /api/workflows/proposals/{id}/approvals
└── flowpilot.workflow.approval
    └── flowpilot.action.execute
```

模型 span 只保存模型名、任务、Token 和 latency；Agent 节点只保存 ticket/creator/video/TraceId 等稳定标识，不保存 Prompt、rationale 或 Evidence 正文。

## 4. 当前边界

- `interrupt()` 是正常人工等待，不记录为错误 span；审批恢复由独立 `workflow.approval` span 表达。
- 本地 TraceId 是业务关联键，不等同于 W3C trace ID；二者通过 span attribute 关联。
- 自动 HTTP/asyncpg/OpenAI instrumentation 与 FlowPilot 自定义业务 span 是父子补充关系。
- 当前没有生产采样、Collector 高可用、告警规则或多实例 trace 验证，不能表述为生产级可观测平台。
