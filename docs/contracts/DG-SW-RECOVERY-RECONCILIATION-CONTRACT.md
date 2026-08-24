# DG—SW 恢复请求幂等与未知结果对账合同（Draft）

> 状态：已决策、待 DG/SW 两侧实现与真实联调。  
> 目标：解决“SW 已接受恢复请求，但 DG 在收到响应或写回 PostgreSQL 前异常”造成的未知结果。  
> 边界：只覆盖 `recover_expired_video_processing`，不扩展为通用远程命令平台。

## 1. 问题定义

DG 当前先提交 `executions.status=running`，再在事务外调用 SW，最后写入
`succeeded/failed`。如果 SW 已完成状态重置和 Outbox 写入，但响应丢失或 DG 在结果
落库前崩溃，DG 无法区分：

- 请求未到达 SW；
- SW 已接受请求但响应丢失；
- SW 明确拒绝了请求；
- SW 暂时不可查询。

这类情况不能直接记为 `failed`，也不能换新幂等键盲目重试。

## 2. 核心语义

1. `Idempotency-Key` 是一次恢复意图的跨项目稳定标识，仍使用：
   `{proposal_id}:recover_expired_video_processing`。
2. SW 必须持久化恢复回执，并以 `idempotency_key` 建唯一约束。
3. SW 的“恢复成功”定义为：任务状态重置、视频状态重置、恢复 Outbox 和
   `ACCEPTED` 回执在同一 MySQL 事务提交；不要求 Processor 已完成转码。
4. 同一 key 重复 POST 必须返回同一 recovery/outbox，不创建第二条恢复消息。
5. DG 对 timeout、连接中断、HTTP 5xx、成功响应无法解析等情况记录 `unknown`，随后按
   同一 key 查询；不能直接记录 `failed`。
6. 查询不到回执时，DG 可以用同一 key 重发 POST。因为 SW 已实现幂等，所以该重发安全。
7. 超过对账次数或时间窗口仍无法确认时，DG 将执行和工单升级人工，不宣称 exactly-once。

## 3. SW 必须实现

### 3.1 持久化表

建议新增 `video_processing_recovery_request`：

```sql
create table video_processing_recovery_request (
    id               bigint primary key,
    idempotency_key  varchar(255) not null,
    video_id         bigint not null,
    requested_by     varchar(64) not null,
    trace_id         varchar(128) not null,
    status           varchar(16) not null,
    reason           varchar(64) null,
    outbox_id        bigint null,
    created_at       datetime not null,
    updated_at       datetime not null,
    unique key uk_video_recovery_idempotency (idempotency_key),
    key idx_video_recovery_video (video_id, created_at)
);
```

持久化状态使用：

- `PENDING`：事务内抢占幂等键的临时状态；事务提交后的正常响应不应暴露该状态。
- `ACCEPTED`：恢复状态变更和 Outbox 已原子提交。
- `REJECTED`：首次请求时业务前置条件不成立，未创建恢复 Outbox。

`reason` 第一版只需要：

- `PRECONDITION_NOT_MET`：任务不存在、不是 `PROCESSING` 或 lease 未过期。

同一 key 对应的 `video_id`、`requested_by` 不允许变化；冲突返回 HTTP 409。

### 3.2 POST 恢复接口

保留路径：

```http
POST /video/api/private/processing/{videoId}/recover-expired
Idempotency-Key: {proposalId}:recover_expired_video_processing
X-Trace-Id: {traceId}
X-FlowPilot-Service: flowpilot
```

三项 Header 均必须非空并限制长度；缺失或非法返回 HTTP 400。服务端身份认证可在后续
单独加固，本增量至少持久化 `requested_by`，不能继续忽略 Header。

响应从 `Result<Boolean>` 改为 `Result<RecoveryOperationResponse>`：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "recoveryId": "193000000000000001",
    "videoId": 7321572775443310,
    "idempotencyKey": "proposal-id:recover_expired_video_processing",
    "status": "ACCEPTED",
    "reason": null,
    "outboxId": "193000000000000002",
    "traceId": "dg-sw-reconcile-demo-1",
    "requestedBy": "flowpilot",
    "replayed": false,
    "createdAt": "2026-08-24T10:00:00"
  }
}
```

重复相同 key 时返回同一 `recoveryId/outboxId/status/createdAt`，仅
`replayed=true`。首次前置条件不成立时返回 `status=REJECTED`、
`reason=PRECONDITION_NOT_MET`，并持久化该拒绝回执；同一 key 后续仍返回该结果，调用方
必须重新调查并创建新 Proposal，不能复用旧 key 等待条件变化。

### 3.3 GET 对账接口

新增：

```http
GET /video/api/private/processing/{videoId}/recovery-status
Idempotency-Key: {proposalId}:recover_expired_video_processing
X-Trace-Id: {traceId}
X-FlowPilot-Service: flowpilot
```

- 找到：返回与 POST 相同的 `RecoveryOperationResponse`，`replayed` 字段可省略或为 true。
- 未找到：HTTP 404；不能返回伪造的 `REJECTED`。
- key 已存在但属于其他 `videoId/requestedBy`：HTTP 409。
- 查询接口只读，不创建 Outbox、不修改任务状态。

### 3.4 SW 事务与并发要求

首次 POST 在一个 MySQL 事务中完成：

```text
INSERT IGNORE PENDING 回执以抢占 idempotency_key
-> 若已存在则读取并校验 video/service 后返回原回执
-> 原子更新 processing task: PROCESSING + expired -> PENDING
-> 原子更新 video: PROCESSING -> PENDING_REVIEW
-> 插入 recovery Outbox
-> 更新回执为 ACCEPTED 并保存 outbox_id
-> commit
```

若业务前置条件不成立，则写入 `REJECTED` 回执后提交，不创建 Outbox。

并发相同 key 由唯一索引收敛：竞争失败者重新读取已提交回执。并发不同 key 指向同一
video 时只能有一个通过状态条件更新；另一个持久化为 `REJECTED`。`createRecoveryOutbox`
需要返回 `outboxId`，用于回执和排障。

自动定时恢复可暂时保持原路径；若它先完成恢复，DG 的首次 POST 会得到稳定的
`REJECTED/PRECONDITION_NOT_MET`。后续可再为自动恢复生成内部幂等键，不阻塞本增量。

### 3.5 SW 文件级改动清单

- `scripts/migrations/V20260825__video_processing_recovery_request.sql`：新表、唯一键和索引；SW 已存在 `V20260824__video_commerce.sql`，不要复用版本号。
- `video/video-pojo/.../entity/VideoProcessingRecoveryRequest.java`：回执实体和状态枚举。
- `video/video-pojo/.../response/VideoRecoveryOperationResponse.java`：稳定响应 DTO。
- `video/video-core/.../mapper/VideoProcessingRecoveryRequestMapper.java`：MyBatis-Plus Mapper。
- `VideoProcessingTaskService.java`：恢复方法改收 idempotency key/service name，并增加只读查询。
- `VideoProcessingTaskServiceImpl.java`：幂等占位、原子恢复、Outbox ID 回传和重复读取。
- `VideoPrivateController.java`：读取三个 Header，POST 返回结构化回执，新增 GET 查询。
- 对应 service/controller 测试：覆盖下述并发、重放和事务回滚合同。

### 3.6 SW 测试要求

- 首次合法请求：ACCEPTED，任务/视频重置，恰好一条 Outbox 和一条回执。
- 同 key 重放：相同 recovery/outbox，`replayed=true`，Outbox 总数仍为 1。
- 同 key 不同 video/service：409。
- 前置条件失败：REJECTED，无 Outbox；重复请求结果稳定。
- GET 找到、GET 404、GET key/video 冲突。
- 两个并发相同 key：最终一条回执、一条 Outbox。
- 回执、状态更新、Outbox 任一步异常：整个事务回滚。

## 4. DG 必须实现

### 4.1 执行状态与工单状态

`executions.status` 扩展为：

```text
pending | running | unknown | succeeded | failed | escalated
```

新增字段：

```text
reconcile_attempts   integer default 0
next_reconcile_at    timestamptz null
last_reconciled_at   timestamptz null
```

新增索引 `(status, next_reconcile_at)`。`result` JSONB 保存经过脱敏的最后一次错误和 SW
回执，不保存 Token/Header。

工单状态新增 `RECONCILING`：

```text
EXECUTING -> RECONCILING
RECONCILING -> RESOLVED | FAILED | ESCALATED
```

### 4.2 异常分类

不能再把所有异常统一记为 failed：

- 明确成功：SW `status=ACCEPTED` -> `succeeded`。
- 明确失败：SW `status=REJECTED`、401/403、参数/合同冲突 -> `failed`。
- 结果未知：timeout、连接中断、HTTP 5xx、已收到但无法解析的成功响应 -> `unknown`。

`unknown` 时 Proposal 不标记 executed，Ticket 进入 `RECONCILING`，写
`execution.unknown` 审计事件。

### 4.3 Runner 合同

`BusinessActionRunner` 增加明确的对账能力，建议接口为：

```python
async def run(proposal: ActionProposal, *, idempotency_key: str) -> dict: ...
async def reconcile(proposal: ActionProposal, *, idempotency_key: str) -> ReconciliationOutcome: ...
```

SW Runner 的 `reconcile`：

1. GET recovery-status。
2. `ACCEPTED` -> succeeded。
3. `REJECTED` -> failed。
4. 404 -> 使用同一 idempotency key 重发 POST，再按结构化回执判断。
5. 查询或重放仍遇到网络/5xx -> 保持 unknown。

Mock Runner 同样实现确定性对账，便于无 SW 自动化测试。

### 4.4 Repository 与对账服务

- `execute_proposal()` 继续先在短事务写 `running`，再事务外调用 Runner。
- 捕获专用 `ActionOutcomeUnknownError` 后，将 execution 原子更新为 `unknown`，设置首次
  `next_reconcile_at`，不伪造失败。
- 新增 `ExecutionReconciliationService.run_once(limit)`：读取到期 unknown 记录、加载原
  Proposal、事务外查询/安全重放，最后条件更新执行与工单状态。
- 对账 GET 和同 key POST 都是幂等的，多副本重复运行不会产生第二个 SW Outbox；数据库
  更新使用 `WHERE status='unknown'` 防止旧结果覆盖终态。
- 指数退避建议：5s、15s、45s、120s；达到 4 次仍未知则 execution=`escalated`、
  ticket=`ESCALATED`，进入人工处理。

### 4.5 API、调度与展示

- 新增只读：`GET /api/tickets/{ticket_id}/executions`。
- 新增受控手工入口：`POST /api/executions/{execution_id}/reconcile`，仅 admin/service。
- FastAPI lifespan 可选启动后台循环，默认配置建议：

```text
FLOWPILOT_RECONCILIATION_ENABLED=false
FLOWPILOT_RECONCILIATION_INTERVAL_SECONDS=5
FLOWPILOT_RECONCILIATION_BATCH_SIZE=50
FLOWPILOT_RECONCILIATION_MAX_ATTEMPTS=4
```

本地 Demo 显式开启，默认关闭避免测试/开发环境隐式产生网络请求。关闭服务时必须 cancel
并 await 后台 task。

工作台增加 execution 状态、对账次数、下一次对账时间；`RECONCILING` 显示为黄色，
`ESCALATED` 显示为红色。手工“立即对账”按钮只在 admin Demo 模式显示。

### 4.6 DG 测试要求

- SW 已接受但 Runner 模拟响应丢失：execution unknown、ticket RECONCILING。
- 对账查询 ACCEPTED：补写 succeeded、proposal executed、ticket RESOLVED、审计完整。
- GET 404 后同 key POST：只产生一次业务恢复并成功收敛。
- SW REJECTED：execution failed、ticket FAILED。
- 连续不可达达到上限：execution/ticket ESCALATED。
- 重复/并发对账不重复副作用、不覆盖终态。
- 401/403/合同冲突属于明确失败，不进入无限对账。
- API RBAC、调度启停、shutdown cancel、OTel 安全属性和工作台状态展示。
- 完整 pytest、Ruff、前端 TypeScript/Vitest/build。

### 4.7 DG 文件级改动清单

- `domain/models.py`：ExecutionRecord 增加对账字段。
- `domain/status.py`：增加 Ticket `RECONCILING` 及合法迁移。
- `action_runner.py`：Runner 接收显式幂等键，增加对账结果类型和未知结果异常。
- `sw_video_recovery.py`：适配 SW 新 POST/GET 回执合同并做异常分类。
- `db/repo.py`：unknown 持久化、到期查询、条件更新、审计和最终状态收敛。
- 新增 `execution_reconciliation.py`：单次对账服务、退避和升级策略。
- `approval_workflow.py`：execution unknown 时把 Ticket 转为 RECONCILING。
- `api/main.py`：可选调度生命周期、执行查询和手工对账 API。
- `docker/postgres/init.sql` 与独立升级 SQL：执行状态/字段/索引迁移；现有本地数据库必须显式执行升级 SQL，不能只修改 init.sql。
- `web/src/app/flowpilot/` 与 API client：展示 unknown/reconciling/escalated 和对账次数。
- `tests/flowpilot/`：领域、Repository、HTTP、调度、SW 客户端和故障注入回归。

## 5. 联调验收

SW 完成后，准备一条带真实 MinIO 对象的隔离过期任务，并暂停自动恢复扫描。DG 使用真实
Runner 发起 POST；在测试 Runner 中模拟“SW 返回 ACCEPTED 后抛连接中断”，让 DG 留在
`unknown/RECONCILING`。随后运行一次 reconcile：

```text
SW GET 根据 idempotency key 返回 ACCEPTED
-> DG execution succeeded
-> proposal executed
-> ticket RESOLVED
-> attempts 仍代表一次业务执行，对账次数单独累计
-> SW recovery receipt 和 Outbox 均只有一条
```

最后恢复 SW 自动扫描配置。记录 TraceId、execution ID、recovery ID、outbox ID、状态迁移和
审计事件，作为简历与面试证据。

## 6. 明确不做

- 不追求分布式事务或宣称 exactly-once。
- 不让 Agent/LLM 决定是否重试。
- 不用新 idempotency key 重试同一 Proposal。
- 不通过 DG 直查 SW 数据库或 Outbox。
- 不把 Processor 最终转码成功与“恢复请求已被 SW 原子接受”混为同一状态。
