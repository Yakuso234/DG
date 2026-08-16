# ADR-001：Agent 运行时选型（MAF 1.0 beta vs LangGraph 1.x + 官方 SDK）

- 状态：已接受
- 日期：2026-08-16（Spike 证据同日完成）
- 决策者：DG 项目（个人秋招项目）
- 相关：`docs/spikes/SPIKE-001-agent-runtime-contract.md`、`spikes/a-maf/`、`spikes/b-langgraph/`

## 1. 背景

上游电商演示底座基于 Microsoft Agent Framework (MAF) 1.0 beta，且存在：

- 需要运行时改写 `site-packages/agent_framework/__init__.py` 的补丁（`agents/python/patch_maf.py`），在中文 Windows 上曾因隐式编码损坏包（见本地面试复盘）。
- 自定义工具调用循环（`shared/agent_host.py` 不用 MAF Responses API，而是手写 chat completions 循环）。
- FlowPilot Phase 1-4 的硬需求：确定性状态机、MCP 工具、**持久化 HITL 跨进程恢复**、Fake Model 可测性、A2A 服务间协作。

因此必须通过同构 Spike 实证：继续 MAF 还是迁移 LangGraph 1.x + 官方 A2A/MCP SDK。

## 2. 决策驱动因素（按优先级）

1. **能力通过性**：S1-S4 与 S5a 是否通过（见 Spike 合同）。
2. **可安装性与无补丁**：全新环境 `uv` 安装是否可复现；是否需要 monkey patch 第三方包。
3. **持久化成熟度**：HITL checkpoint 是否为框架官方支持、存储介质、跨进程恢复路径。
4. **可测试性**：Fake Model 注入难度、测试时延。
5. **生态与迁移成本**：现有上游代码复用率、团队（个人）学习成本、Python 3.12/3.14 兼容。
6. **非目标**：不使用"更新/更流行"作为理由。

## 3. 候选方案

### 方案 A：保留 MAF 1.0 beta

- 复用上游 agent_host、prompt_loader、A2A server 配置。
- 风险：beta API 不稳定、需补丁、checkpoint/HITL 官方能力未知。

### 方案 B：LangGraph 1.x + 官方 a2a-sdk + 官方 mcp sdk

- 官方 checkpoint（SQLite/Postgres）、interrupt/HITL 一等公民。
- 成本：重写 Agent 胶水层，A2A/MCP 需按官方 SDK 重新接。

## 4. 证据

两套实现均按同构合同完成，验收命令退出码均为 0。完整证据见 `spikes/a-maf/{report.json,EVIDENCE.md}` 与 `spikes/b-langgraph/{report.json,EVIDENCE.md}`。

| 维度 | A：MAF 1.0（`spikes/a-maf/`） | B：LangGraph 1.x（`spikes/b-langgraph/`） |
|---|---|---|
| 场景通过 | S1-S4、S5a、S5b 全 PASS（16 tests，3.81s） | S1-S4、S5a、S5b 全 PASS（11 tests，3.28s） |
| Python | 3.14.2 原生可用 | 3.14.2 原生可用 |
| monkeypatches | 空（新版公共 API 打包缺陷已修复，新装无需 patch_maf） | 空 |
| 依赖体积 | `agent-framework==1.0.0` 为元包：155 包约 200MB，含无关 provider SDK（github-copilot 51.6MB、claude-agent 71.5MB） | 75 包；langgraph 1.2.11 + checkpoint-sqlite 3.1.1 + mcp 2.0.0 + a2a-sdk 1.1.2 |
| Checkpoint | 官方 `FileCheckpointStorage` 支持跨进程恢复，但序列化用 **pickle**（官方 docstring 自注反序列化不安全）；领域审批门需应用层 JSON 落盘 | 官方 `SqliteSaver`（SQLite + JsonPlusSerializer），跨进程恢复无坑；审批门即图状态的一部分 |
| HITL | `request_info` + `@response_handler` 可用；但导入期严格校验 `WorkflowContext` 泛型，本次已遇 `None→Never` 行为漂移 | `interrupt()` + `Command(resume)` 一等公民，文档完备 |
| 结构化输出 | 可用，glue 596 行 | 可用，glue 474 行 |
| 稳定性风险 | 1.0.0 beta 行为已漂移（`__init__.py` 修复、泛型收紧），历史上有 Windows 编码损坏补丁事件 | 1.x 稳定版，官方文档与示例覆盖 checkpoint/HITL |

## 5. 决策

**采用方案 B：LangGraph 1.x + 官方 a2a-sdk + 官方 mcp SDK 作为 FlowPilot 的 Agent 运行时。**

决策依据（按 ADR §2 优先级排序）：

1. **持久化成熟度与安全（决定性）**：FlowPilot 红线要求"持久化审批、证据可追溯、防注入"。LangGraph 官方 SqliteSaver/Postgres checkpointer 用 JSON 序列化、跨进程恢复实测无坑；MAF 的 FileCheckpointStorage 用 pickle，官方自注不可加载不可信来源——checkpoint 若被提示注入投毒，恢复即反序列化风险，与安全红线冲突。MAF 侧领域审批门事实上也要应用层自研落盘，等于自带两套持久化。
2. **可安装性**：MAF 元包强制安装 155 包/约 200MB 无关 provider SDK；LangGraph 依赖收敛（75 包），`uv.lock` 可复现。
3. **稳定性**：MAF 1.0.0 beta 在本次 Spike 周期内已暴露行为漂移（`WorkflowContext` 泛型 `None→Never`、导入期校验、`__init__.py` 变化）；LangGraph 1.x 为稳定版。
4. **生态与迁移成本可控**：上游 MAF 胶水层（agent_host/session/checkpoint_storage/workflow_loader/remote_agent/patch_maf）按保留清单 §2.4 逐模块替换；框架无关资产（db/config/context/auth/prompt_loader/guardrails/telemetry/MCP 包骨架/前端 shell）不受影响。Spike B 证明核心链路（状态机+MCP+HITL+A2A）474 行胶水即可跑通。

明确记录的非决策理由：不使用"LangGraph 更新/更流行"作为理由；两套栈能力层面（S1-S5b）均通过，本决策差异集中在安全、依赖收敛与稳定性证据上。

## 6. 后果与回退

**正面后果**：

- HITL/checkpoint 为框架一等公民，Phase 4 的"重启恢复、不重复执行"有官方保障与文档。
- 依赖收敛，Docker 镜像与 CI 更轻；无 site-packages 补丁，安装可复现。
- Prompt 注入→checkpoint 投毒风险被 JSON 序列化从默认路径排除。
- 面试可解释性强：LangGraph 的 interrupt/Command、SqliteSaver 是 Agent 岗高频考察点，且都有本项目实测证据。

**负面后果（接受）**：

- 上游 MAF 胶水层（约 13 个模块，见保留清单 §2.4）需删除或重写，orchestrator 的 SSE 流式链路要用官方 A2A SDK 重建；Phase 3 开始前需先完成这一替换。
- 团队（个人）需投入 LangGraph 学习成本（Spike B 已覆盖核心路径）。
- 上游 `agent-framework` 相关教程/文档全部作废（已列入删除批 1）。

## 7. 回退路径

- Spike A 证据永久保留（`spikes/a-maf/`），它证明 MAF 1.0 同样覆盖 S1-S5b 全部硬需求。
- 若 LangGraph 在 Phase 3 大规模集成遇到阻塞（超过 1 个工作日的不可解问题），可回退 MAF；回退时的强制条件：不使用 pickle checkpoint（改用 JSON 应用层持久化或仅用 FileCheckpointStorage 存不可信标记状态），并重新评估元包依赖体积。
- 电商代码删除批 1（.NET/tutorials/dotnet-compose）与本选型无关，任何情况下都可先行执行。
