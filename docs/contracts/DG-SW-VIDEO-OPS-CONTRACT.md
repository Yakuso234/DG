# DG 到 SW Video Ops 合同（P2/P4）

## 边界

- SW 与 DG 是独立项目；DG 不读取 SW 的 MySQL、Redis、RabbitMQ。
- `sw-video-ops-mcp` 永远只读，不提供恢复、发布、删除或中间件操作工具。
- 写恢复只能由 DG Action Executor 发起；必须经过提案持久化、人工审批、
  checkpoint 匹配、幂等占位和审计开始事件。

## SW 私有读取接口

| MCP 工具 | SW HTTP 接口 | 用途 |
|---|---|---|
| `get_video_processing_status` | `GET /video/api/private/creator/{creatorId}/processing/{videoId}` | 读取创作者范围内的视频/处理任务状态、重试、租约和受限失败摘要 |
| `get_processing_operations_overview` | `GET /video/api/private/processing/operations/overview` | 读取队列、处理中与失败任务计数 |

DG 的 Investigation 可选择两种只读 transport：默认 `direct-http` 直连上表的
私有 HTTP，或配置 `FLOWPILOT_SW_OPS_TRANSPORT=mcp` 后以官方 MCP
`ClientSession` 访问 `SW_VIDEO_MCP_URL`（Streamable HTTP，默认 `/mcp`）。两者
都归一为相同的 `SwVideoOpsGateway` 合同；direct HTTP、MCP client 与恢复执行器
对服务调用均禁用环境代理，避免 loopback/private endpoint 被系统代理意外转发。

DG 只接受 SW 的 `Result<data>` JSON 响应；缺少必要字段、非 JSON 或异常状态统一转为结构化调用失败，不能被模型当作事实。

## SW 私有恢复接口

| Action Catalog 动作 | SW HTTP 接口 | 原子业务语义 |
|---|---|---|
| `recover_expired_video_processing` | `POST /video/api/private/processing/{videoId}/recover-expired` | 仅将“租约已过期且仍为 PROCESSING”的任务恢复为 PENDING，并在同一事务生成新的 Outbox 消息 |

该动作的参数合同固定为：

```json
{
  "ticket_id": "<FlowPilot ticket UUID>",
  "creator_id": 7,
  "video_id": 901,
  "trace_id": "trace-demo-1"
}
```

这些字段由调查证据绑定。审批人不能通过 `modified_params` 更换工单、创作者、
视频或 TraceId；若目标需要变化，必须重新调查并生成新提案。

SW 返回持久化的 `Result<VideoRecoveryOperationResponse>`，其中回执状态只能是
`ACCEPTED` 或 `REJECTED`，并包含 `recoveryId`、`outboxId`（仅 ACCEPTED）、
原始幂等键与 TraceId。DG 只有在 `ACCEPTED` 时记为成功；`REJECTED` 是明确的
业务失败。timeout、5xx、断连或成功报文无法解析时不能把 HTTP 状态当业务结论，
必须把 Execution 置为 `unknown`，通过同一幂等键查询：

```text
GET /video/api/private/processing/{videoId}/recovery-status
```

查询 `ACCEPTED` 补写成功，`REJECTED` 明确失败；仅在 404 时用原 key 安全重发 POST。
完整字段和对账状态机见 `DG-SW-RECOVERY-RECONCILIATION-CONTRACT.md`。

## 服务身份与追踪

每次 DG 到 SW 的请求必须带：

```text
Authorization: Bearer ${SW_VIDEO_SERVICE_TOKEN}
X-FlowPilot-Service: flowpilot
X-Trace-Id: ${trace_id}
Idempotency-Key: ${proposal_id}:recover_expired_video_processing
```

DG 在缺少 Token 时失败关闭，不会发送匿名请求。MCP mode 的服务身份头由 MCP
client 发往 MCP server，TraceId 作为工具参数传递，再由 server 的下游 SW HTTP
gateway 发送 `X-Trace-Id`。写动作默认仍使用本地 Mock；只有显式设置
`FLOWPILOT_ACTION_RUNNER=sw-video-recovery` 才启用真实 SW 适配器。

SW 当前私有路由只由 Gateway 隔离公网；JWT/mTLS 不在本轮范围。SW 本地实现会持久化
`Idempotency-Key` 回执并验证其与 video/service 的一致性，但这不等同于生产服务身份
认证或跨项目 exactly-once。2026-08-23 已以隔离的过期 `PROCESSING` lease 完成一次
真实 HTTP 闭环；后续对账演练需按 SW `DEMO_RUNBOOK.md` 暂停自动恢复扫描。

## Evidence 归一

MCP 状态工具结果进入 DG 时统一写为：

- `source = sw-video-ops-mcp`
- `tool = get_video_processing_status`
- 数据包含 `creator_id`、`video_id`、视频/处理状态、重试次数、租约、受限错误摘要、来源系统与 TraceId。

## 禁止事项

- 不经 MCP/HTTP 合同直接访问 SW 数据或消息中间件。
- 不把 `recover-expired` 暴露为 LLM MCP Tool。
- 不使用不可逆或生产级动作作为本地秋招 Demo。
