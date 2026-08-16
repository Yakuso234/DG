# SPIKE-001：Agent 运行时选型同构合同

> 日期：2026-08-16  
> 目的：在相同验收场景下比较 **A = MAF 1.0 beta（现有底座）** 与 **B = LangGraph 1.x + 官方 a2a-sdk + 官方 mcp sdk**，为 ADR-001 提供可复现证据。  
> 结论只接受证据，不接受"更新/更流行"作为理由。

## 1. 验证范围（为什么是这五个场景）

FlowPilot Phase 1-4 的硬需求可归纳为五项必须能力，本 Spike 逐一验证：

| 场景 | 对应路线图需求 | 必须/尽力 |
|---|---|---|
| S1 确定性状态机 | Phase 1：非法转移拒绝、领域代码与 LLM 解耦 | 必须 |
| S2 MCP 读工具 | Phase 2：工具带 Schema 与来源证据 | 必须 |
| S3 持久化 HITL 恢复 | Phase 4：进程重启后恢复到审批点、不重复执行 | 必须 |
| S4 Fake Model 全链路 | 无 Key/无网络可测试、可复现 | 必须 |
| S5 A2A 边界 | 服务间协作；5a 内存 transport 必须，5b 跨进程 HTTP 尽力 | 必须+尽力 |

## 2. 同构约束

1. **共享领域核心**：两套实现都必须直接 import `spikes/shared/domain.py`（纯 Python，零框架依赖），不得各自重写语义不同的状态机/证据/方案模型。
2. **统一 Fake Model 行为**（见第 4 节）：任何网络调用尝试 = 该场景失败。
3. **统一验收命令**：`cd spikes/<stack> && uv run pytest -q`，退出码 0 才计入通过。
4. **统一报告**：测试完成后 `spikes/<stack>/report.json` 必须存在，字段见第 5 节。
5. **统一环境**：Windows + uv。两套默认用 Python 3.14（本机已装）；若某栈不兼容 3.14，则该栈改用 uv 下载的 3.12，并把"3.14 不兼容"记入 `EVIDENCE.md` 扣分项，同时另一栈也用 3.12 重跑保持同构。

## 3. 共享领域核心（spikes/shared/domain.py）

- `TicketStatus`：`NEW -> TRIAGED -> INVESTIGATING -> PROPOSED -> WAITING_APPROVAL -> EXECUTING -> RESOLVED/ESCALATED/FAILED`。
- `LEGAL_TRANSITIONS`：唯一合法转移表；任何非法转移抛 `IllegalTransitionError`。
- `Ticket`：id、title、status、evidence（Evidence 列表）、proposal、approval、executed 列表；提供 `to_json`/`from_json`（序列化恢复的唯一依据）。
- `Evidence`：tool、source（MCP 服务名）、data、collected_at（ISO 8601 UTC）；必须有来源与时间，不允许匿名证据。
- `ActionProposal`：action、params、evidence_tools、risk（`low`|`high`）。
- `EXECUTION_RULE`：共享执行器语义——`risk == "high"` 的提案必须在 `approval == "approved"` 之后才可执行；未审批执行抛 `ApprovalRequiredError`。

## 4. 统一 Fake Model 行为规范

Fake Model 是无网络、确定性的模型替身，两套实现行为必须一致：

1. 第一轮：返回一个工具调用 `get_ticket_status(ticket_id="T-1001")`。
2. 第二轮（拿到工具结果后）：产出固定处置方案 `ActionProposal(action="restart_pipeline", params={"ticket_id": "T-1001"}, evidence_tools=("get_ticket_status",), risk="high")`，并停止。
3. 不得发起任何 HTTP/DNS；不得读取环境变量中的真实 Key。

## 5. 验收场景与断言

### S1 确定性状态机（无 LLM）

- `NEW -> TRIAGED -> INVESTIGATING -> PROPOSED -> WAITING_APPROVAL` 逐级转移全部成功。
- `NEW -> RESOLVED`、`RESOLVED -> PROPOSED` 等非法转移抛 `IllegalTransitionError`。
- `Ticket.to_json -> Ticket.from_json` 往返后字段完全一致（含 evidence、proposal）。

### S2 MCP 读工具

- 用官方 MCP SDK 起一个最小 MCP server（内存 transport），暴露 `get_ticket_status(ticket_id)` 读工具，返回确定性 JSON。
- 由 Fake Model 驱动一次工具调用；工具返回被归一为 `Evidence(tool="get_ticket_status", source=<mcp server 名>, collected_at=...)` 并存入 `Ticket.evidence`。
- 断言：evidence 长度 1；evidence.tool/source/data 正确；collected_at 为 UTC ISO 格式。
- 断言：向读工具传非法 ticket_id 时返回结构化错误（不为空、不含堆栈）。

### S3 持久化 HITL 恢复

固定剧本（两个"进程"）：

1. **进程 1**：Ticket T-1001 走完调查，产出 `risk="high"` 的 ActionProposal，进入 `WAITING_APPROVAL`，把状态持久化后**彻底销毁运行时对象**（模拟进程被杀）。
2. **进程 2**（新运行时对象/新进程）：从持久化恢复，断言恢复点状态为 `WAITING_APPROVAL` 且 evidence 完整。
3. **未审批先行**：进程 2 在 approval 为空时调用执行器，断言抛 `ApprovalRequiredError`（高风险不能绕过审批）。
4. **审批后继续**：approval 置为 `"approved"` 后执行器执行，`executed` 列表恰好包含一次 `restart_pipeline`；状态到 `RESOLVED`。
5. **不重复执行**：恢复/重放后 `executed` 长度仍为 1（相同逻辑步骤不得二次执行）。

### S4 Fake Model 全链路

- 无网络、无任何真实 Key 的环境中，`uv run pytest -q` 跑通 S1-S3 全部用例。
- 用例中不得出现真实 LLM 客户端构造（若框架强制要求，必须如实记录为扣分项）。

### S5 A2A 边界

- **5a（必须）**：用本栈 A2A SDK 的内存 transport 完成 AgentCard 获取 + `message:send` 往返，收到结构化（可 JSON 解析）响应。
- **5b（尽力）**：把同一 Agent 以 HTTP 暴露到本机端口，用官方客户端完成一次往返。成功记 PASS，失败记 `SKIPPED-WITH-REASON`，不否决但扣分，并在 `EVIDENCE.md` 写清失败原因。

## 6. report.json 必含字段

```json
{
  "stack": "a-maf | b-langgraph",
  "python": "3.14 | 3.12",
  "scenarios": {"S1": "PASS|FAIL", "S2": "PASS|FAIL", "S3": "PASS|FAIL", "S4": "PASS|FAIL", "S5a": "PASS|FAIL", "S5b": "PASS|SKIPPED-WITH-REASON|FAIL"},
  "pytest_exit_code": 0,
  "duration_seconds": 12.3,
  "deps": {"langgraph": "...", "agent-framework": "...", "mcp": "...", "a2a-sdk": "..."},
  "glue_lines": 123,
  "monkeypatches": ["描述任何对 site-packages/第三方包的改写"]
}
```

`glue_lines` = 该栈除 `spikes/shared/` 与测试文件外的实现代码行数。

## 7. EVIDENCE.md 必记内容

每套实现写 `spikes/<stack>/EVIDENCE.md`，必须包含：

1. 安装命令与依赖清单（uv lock 是否成功、是否被迫改依赖范围）。
2. Checkpoint/持久化实现方式：框架内置 or 自研？存储介质（SQLite/内存/其他）？跨进程恢复是否被框架官方支持？
3. 结构化输出机制与失败时的行为。
4. S5b 结论与原因。
5. Windows/Docker 备注、测试总耗时、修复次数与最耗时的坑。
6. 对 FlowPilot Phase 1-4 的适配性判断（证据+判断分开写）。

## 8. 判定规则

- S1-S4 与 S5a 必须 PASS；S5b 失败不否决但计入扣分。
- `monkeypatches` 非空、checkpoint 非官方持久化、3.14 不兼容、S5b 失败均计扣分。
- ADR-001 综合：能力通过性 > 无补丁/可安装性 > 持久化成熟度 > 生态与迁移成本。
- 两套都不能通过时，ADR 记录失败原因并选择迁移成本较低者 + 补强方案，不得凭偏好定案。
