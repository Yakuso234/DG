# EVIDENCE — SPIKE-001 Spike A: Microsoft Agent Framework (MAF) 1.0

> 验收命令：`cd spikes/a-maf && uv run pytest -q` → **exit 0**（16 passed）
> 结论总览：**S1–S5b 全部 PASS**；`monkeypatches = []`；Python 3.14.2 原生可用（未回退 3.12）。

---

## 1. 安装命令与依赖清单

**安装命令（在 `spikes/a-maf/` 下）：**

```powershell
# 环境：Windows 中文系统，Python 3.14.2（C:\Program Files\pythondevelop\python.exe），uv 0.12.5
# uv 缓存目录被本机 ACL 拒绝，重定向到临时目录：
$env:UV_CACHE_DIR = "$env:TEMP\uv-cache-dg"

uv init --name a-maf --python 3.14 --vcs none      # 后改为手写 pyproject + uv sync
uv sync                                             # 解析 155 个包，全部安装成功，生成 uv.lock（356 KB）
```

**直接依赖（`pyproject.toml`）：**

| 包 | 固定版本 | 用途 |
|---|---|---|
| `agent-framework` | `==1.0.0` | MAF 核心（本 spike 的被测对象） |
| `mcp` | `==1.27.0` | S2 官方 MCP SDK（内存 transport） |
| `a2a-sdk` | `==0.3.23` | S5 官方 A2A SDK |
| `pytest` / `pytest-asyncio` | `>=8.0` / `>=0.24` | dev 组 |

**关键事实（决定 `monkeypatches` 字段）：**

1. **`uv lock` 成功，未被迫修改任何依赖范围**；Python 3.14 全程可用，**没有回退到 3.12**。
2. **公共 API 全新安装后可直接导入 —— 不需要任何 site-packages 补丁。**
   全新安装后 `agent_framework/__init__.py` 是一个 **11 KB 的完整 re-export**（`from agent_framework import Agent, BaseChatClient, tool, FileCheckpointStorage, WorkflowBuilder, Executor, handler, response_handler, WorkflowContext, ...` 全部可用）。
   仓库里 `agents/python/patch_maf.py` 与 `tutorials/_shared/maf_bootstrap.py` 针对的"`__init__.py` 为空"的打包缺陷，**在当前发布的版本里已经修复**。因此本 spike 的 `monkeypatches = []`。
3. **`agent-framework==1.0.0` 在 PyPI 上已变为"元包"**：它实际由 `agent-framework-core==1.0.0`（真正的实现）加上**全部 provider 子包**（`agent-framework-anthropic`、`-azure-*`、`-openai`、`-ollama`、`-bedrock`、`-github-copilot`、`-claude`、`-mem0`、`-redis`、`-foundry` …）组成。代价是：**155 个包、约 200MB 下载**（其中 `github-copilot-sdk` 51.6MB、`claude-agent-sdk` 71.5MB），即便本 spike 只用到了核心 workflow/checkpoint 部分。这是 MAF 1.0 明显的"重依赖"扣分点。

---

## 2. Checkpoint / 持久化实现方式

**结论：MAF 1.0 有官方内置的 checkpoint 持久化机制，且官方支持跨进程/跨实例恢复。** 本 spike 用两条路径如实验证：

### (a) 框架内置（官方）—— `FileCheckpointStorage`

- 位于 `agent_framework._workflows._checkpoint`（现已通过公共 API 导出），另有 `InMemoryCheckpointStorage`。
- `FileCheckpointStorage`：**JSON 元数据 + pickle 编码的执行器状态（base64 内嵌）**，原子写入（`os.replace`）。⚠️ 官方 docstring 明确告警 **pickle 反序列化不安全**，只能加载可信来源的 checkpoint。
- **跨进程恢复是官方设计的**：`WorkflowCheckpoint` 明确记录"checkpoint 不绑定某个 workflow 实例，而是绑定 `workflow_name + graph_signature_hash`"，因此**全新进程/全新实例**可 `load(checkpoint_id)` 后继续执行。
- `WorkflowCheckpoint.pending_request_info_events` 字段表明 **HITL 的 `request_info` 挂起点也是可被 checkpoint 的一等状态**。

验证测试：`test_s3_maf_file_checkpoint_storage_cross_instance`（全新 `FileCheckpointStorage` + 全新 workflow、错误 seed，从首个 checkpoint 恢复后状态与原始一致）；`test_s3_maf_hitl_request_info_pause_and_resume`（`request_info` 挂起 → `responses={id: ...}` 恢复）。

### (b) 应用层自研 —— `Ticket.to_json/from_json`（S3 审批门）

- 审批状态（`Ticket.approval`）与证据/提案都住在共享领域对象里，而不是 MAF 执行器里。因此 S3 的"进程 1 挂起并销毁 → 进程 2 恢复 → 未审批拒绝 → 审批后执行 → 幂等"剧本，用 `shared` 的 `Ticket.to_json`/`from_json` 落盘到 `spikes/a-maf/data/`（`ticket_store.py`）。
- 这是合同 §5 S3 明确允许的路径（"如果不支持或不可靠，允许用应用层文件持久化"）。判断：MAF 官方 checkpoint 成熟、可跨进程，但**它针对的是 workflow 执行器状态**；领域审批门用领域序列化更直接，二者并不冲突。

**存储介质**：两者都是**本地文件**（JSON；MAF checkpoint 为 JSON+pickle）。

---

## 3. 结构化输出机制与失败时的行为

- **Fake Model**（合同 §4）：纯数据类替身，第 1 轮返回工具调用 `get_ticket_status(ticket_id="T-1001")`，第 2 轮返回强类型 `ActionProposal(action="restart_pipeline", risk="high")`，随后 `StopIteration` 停止。**零网络、零 `os.environ`、零真实 LLM 客户端**。
- **MCP 工具**：成功返回 `structuredContent`（JSON dict，确定性）；非法 `ticket_id` 返回 `CallToolResult(isError=True)`，内容是 JSON 文本、**不含堆栈**（`test_s2_illegal_ticket_id_returns_structured_error`）。
- **A2A**：`Message`（Pydantic 模型）经 `model_dump_json()` 得到可 JSON 解析的结构化响应。
- **失败行为**：MAF 的 `@handler` / `@response_handler` 在**导入期**严格校验 `WorkflowContext` 泛型签名（见 §5 坑 4）；非法状态转移抛 `IllegalTransitionError`，高风险未审批执行抛 `ApprovalRequiredError`。

---

## 4. S5b 结论与原因

**PASS**（尽力而为场景，实际通过）。

- 服务端：官方 `A2AStarletteApplication`（内部包 `JSONRPCHandler`）＋ `DefaultRequestHandler`（`InMemoryTaskStore` + `InMemoryQueueManager`）＋ uvicorn 绑定 `127.0.0.1:<空闲端口>`。
- 客户端：官方 `a2a.client.ClientFactory.connect(url)` 完成 `get_card()` + `send_message()`，收到结构化 `Message`。
- 唯一踩坑：最初把 AgentCard 的 `url` 写成 `http://127.0.0.1:0`（port 0），客户端据此重连 port 0 → "All connection attempts failed"。改为先 `socket.bind(("127.0.0.1",0))` 抢占空闲端口、再用真实端口构造 card 后通过。

---

## 5. Windows 备注 / 测试总耗时 / 修复次数 / 最耗时的坑

**测试总耗时**：约 **3.8s**（16 个用例）。**修复迭代**：约 **6 轮**。

按耗时排序的坑：

1. **MAF 1.0 的 `WorkflowContext` 泛型在导入期被严格校验（最大坑）**
   - 报错：`WorkflowContext[None, str]` 被拒（新版要求用 `typing.Never` 表示"无消息/无输出"）。
   - 且 `from __future__ import annotations` 会把注解变成字符串，导致 MAF 运行期 `get_origin()` 内省失败。
   - 修法：`maf_workflow.py` **移除 `from __future__ import annotations`**，并把 `None` 改为 `Never`（`WorkflowContext[str]` / `WorkflowContext[Never, str]`）。
2. **pytest `tmp_path` 与 DSH 沙箱冲突**：系统临时目录 `AppData\Local\Temp\...\pytest-of-52373` 创建被拒（`[WinError 5]`）。修法：在 `conftest.py` 里**覆盖 `tmp_path` fixture**，改在 workspace 内 `.spike-tmp/` 下建目录（`mkdir`/`shutil.rmtree` 自管）。
   - 附产物：一次 `--basetemp=.pytest-tmp` 的失败尝试把 `.pytest-tmp` 目录留成了"毒目录"（沙箱对它的所有操作都拒绝，无法删除）。已弃用该名、加入 `.gitignore`（`data/*.json`、`.pytest-tmp/`、`.spike-tmp/` 均已忽略）。
3. **`uv init` 触发 "spawn node.exe ENOENT"**（其 git 集成在中文 Windows 下异常）→ 用 `--vcs none`，最终改为手写 `pyproject.toml` + `uv sync`。
4. **uv 缓存目录 ACL 拒绝**（`AppData\Local\uv\cache` 拒绝访问）→ 每处命令设置 `$env:UV_CACHE_DIR` 重定向。
5. **pytest 9 移除 `CallInfo.failed`** → `pytest_runtest_makereport` 改用 `call.excinfo`。

**Docker 备注**：本 spike 全程裸机 Windows + uv，未使用 Docker。

---

## 6. 对 FlowPilot Phase 1–4 的适配性判断（证据与判断分开）

**证据（本 spike 实测）：**

- Phase 1 确定性状态机：`spikes/shared/domain.py` 纯 Python 零框架依赖，状态机/`IllegalTransitionError`/JSON 往返与 MAF 完全解耦，S1 全绿。
- Phase 2 MCP 读工具：官方 `mcp==1.27.0` 内存 transport（`create_connected_server_and_client_session`）可用；但 **MAF 自带的 MCP 工具只有 `MCPStdioTool` / `MCPStreamableHTTPTool` / `MCPWebsocketTool`，没有内存 transport 变体**，所以 S2 用 mcp SDK 直连 + 自写确定性工具循环（glue），结果归一为 `Evidence`。
- Phase 3 持久化 HITL：MAF 官方 `request_info`/`@response_handler` HITL 与 `FileCheckpointStorage` 均实测可用、可跨实例恢复；但审批门状态在领域对象里，用 `Ticket.to_json/from_json` 应用层落盘最直接。
- Phase 4 A2A：官方 `a2a-sdk` 内存 transport（自实现 `ClientTransport` 桥接 `RequestHandler`）+ HTTP（官方 `A2AStarletteApplication`）均 PASS；`agent-framework-a2a` 存在但只是 HTTP 绑定，S5a 用 a2a-sdk 直连即可。

**判断（ADR 输入）：**

1. **能力通过性：高。** S1–S5b 全 PASS，HITL/checkpoint/A2A 都有官方或官方可扩展机制。
2. **可安装性：中偏下。** 公共 API 已修复、无需补丁（加分）；但 `agent-framework` 元包把整个 provider 生态（约 155 包 / 200MB）一次拉满，冷启动与体积成本显著（扣分）。
3. **持久化成熟度：中。** 官方 checkpoint 跨进程可用，但用 **pickle**（官方自注安全风险），生产需换/自实现安全存储；审批门这类领域状态仍要应用层持久化。
4. **生态与迁移成本：中。** 类型校验严格（`WorkflowContext`/`Never`）、导入期校验、文档以 underscore 模块演进，beta 版本行为会变（本次就遇到 `None→Never` 与 `__init__.py` 变化），迁移与升级需留意版本漂移。

**建议**：MAF 1.0 能覆盖 Phase 1–4 硬需求，无补丁障碍；主要顾虑是依赖体积与 pickle checkpoint 的安全边界。若追求轻量与可控持久化，需评估 `agent-framework-core` 单独安装（只装核心、不装 provider 子包）是否能满足，作为下一轮 spike 或 ADR 的待验证项。

---

### 附：目录结构

```
spikes/a-maf/
├── pyproject.toml          # uv 项目（Python 3.14，固定 MAF/MCP/A2A 版本）
├── uv.lock                 # 锁定 155 个包
├── report.json             # 验收报告（pytest 结束后自动生成）
├── EVIDENCE.md             # 本文件
├── src/a_maf/              # 实现（glue）代码（除 shared 与测试外，glue_lines=596）
│   ├── fake_model.py       # 确定性无网络 Fake Model（合同 §4）
│   ├── mcp_server.py       # 官方 mcp SDK 内存 server + get_ticket_status
│   ├── ticket_store.py     # Ticket.to_json/from_json 应用层落盘
│   ├── ticket_flow.py      # 调查流水线（S2/S3/S4 共用）
│   ├── maf_workflow.py     # MAF FileCheckpointStorage + request_info HITL 探针
│   └── a2a_agent.py        # A2A 内存 transport + AgentCard + message:send
└── tests/
    ├── conftest.py         # sys.path(spikes/) + tmp_path 覆盖 + report.json 生成
    ├── test_s1_state_machine.py
    ├── test_s2_mcp_read_tool.py
    ├── test_s3_hitl_persistence.py
    ├── test_s4_fake_model.py
    └── test_s5_a2a.py      # S5a 内存 + S5b HTTP
```
