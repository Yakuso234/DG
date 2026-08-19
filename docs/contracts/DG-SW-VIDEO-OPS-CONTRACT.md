# DG 到 SW Video Ops 合同（P2）

## 边界

- SW 与 DG 是独立项目；DG 不读取 SW 的 MySQL、Redis、RabbitMQ。
- `sw-video-ops-mcp` 只读，不提供恢复、发布、删除或中间件操作工具。
- 写恢复留给后续 DG Action Executor；必须经过审批和幂等校验。

## SW 私有读取接口

| MCP 工具 | SW HTTP 接口 | 用途 |
|---|---|---|
| `get_video_processing_status` | `GET /video/api/private/creator/{creatorId}/processing/{videoId}` | 读取创作者范围内的视频/处理任务状态、重试、租约和受限失败摘要 |
| `get_processing_operations_overview` | `GET /video/api/private/processing/operations/overview` | 读取队列、处理中与失败任务计数 |

DG 只接受 SW 的 `Result<data>` JSON 响应；缺少必要字段、非 JSON 或异常状态统一转为结构化调用失败，不能被模型当作事实。

## 服务身份与追踪

每次 DG 到 SW 的请求必须带：

```text
Authorization: Bearer ${SW_VIDEO_SERVICE_TOKEN}
X-FlowPilot-Service: flowpilot
X-Trace-Id: ${trace_id}
```

DG 在缺少 Token 时失败关闭，不会发送匿名请求。SW 当前私有路由只由 Gateway 阻断公网访问，尚未实现上述 Token 的服务端验证；因此当前实现只能证明 DG 出站身份和合同，不得宣称跨项目零信任联调已完成。

## Evidence 归一

MCP 状态工具结果进入 DG 时统一写为：

- `source = sw-video-ops-mcp`
- `tool = get_video_processing_status`
- 数据包含 `creator_id`、`video_id`、视频/处理状态、重试次数、租约、受限错误摘要、来源系统与 TraceId。

## 禁止事项

- 不经 MCP/HTTP 合同直接访问 SW 数据或消息中间件。
- 不把 `recover-expired` 暴露为 LLM MCP Tool。
- 不使用不可逆或生产级动作作为本地秋招 Demo。
