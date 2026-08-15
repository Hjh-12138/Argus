# AgentTeams LoongSuite OTel 观测接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AgentTeams 引擎（Manager + 6 Worker 的 OpenClaw runtime）接入 LoongSuite `opentelemetry-instrumentation-openclaw` 插件，把 LLM 调用/agent 调用/工具调用的 trace + token 用量导出到本地自托管 Jaeger，验证 token 可采、P4 脱敏成立，并补一个按 agent 聚合 token/耗时/error 率的读取器（R4.2 观测层被跳过后的最小落地）。

**Architecture:** AgentTeams 的 Manager 与 Worker 均以 OpenClaw 为 runtime（`contract.lock.json` 的 `runtime: openclaw`；openclaw.json 已有 `plugins.entries` + `load.paths: [/opt/openclaw/extensions/matrix, …]`），LLM 调用全部发生在容器内 OpenClaw 侧（经 agentteams AI 网关路由到 deepseek/claude/glm/qwen）。LoongSuite 的 `opentelemetry-instrumentation-openclaw` 正是 OpenClaw 原生网关插件：装到 `$HOME/.openclaw/extensions/`、写 `plugins.entries`，生成 `enter_ai_application_system → invoke_agent(AGENT) → react(STEP) → chat(LLM)/execute_tool(TOOL)` 的 GenAI semconv span，token 数在 `gen_ai.usage.input_tokens/output_tokens`。最小路径 = 插件装进 Manager + Worker，OTLP 导出到同 docker 网络的本地 Jaeger；P4 要求关闭 conversation access（`hooks.allowConversationAccess=false`），让 OpenClaw 安全策略挡住 `llm_input/llm_output` 正文捕获——只留结构 + token，不落 prompt/源码。**durable 化**：openclaw.json 由 controller 重写（有 `.clobbered` 备份），本仓库侧把插件配置条目做成可复现的纯函数生成器（`agentteams/otel_config.py`），spike 阶段手动落配置、后续再进 controller 的 `generator.go`/template。

**Tech Stack:** Python 3.13, pytest, Docker/AgentTeams v1.2.0-beta.1 (OpenClaw runtime, local_only), LoongSuite `loongsuite-js/opentelemetry-instrumentation-openclaw`, Jaeger all-in-one (OTLP HTTP), OpenTelemetry GenAI semantic conventions.

## Background（已确认的运行时拓扑）

| 事实 | 证据 |
|---|---|
| Manager + 6 Worker 都是 OpenClaw runtime | `agentteams/contract.lock.json`: `runtime: openclaw`；`D:\AgentTeams\config\install-profile.json`: `runtime.manager=openclaw, default_worker=openclaw` |
| LLM 调用在容器内 OpenClaw 侧 | `D:\AgentTeams\manager-workspace\openclaw.json` 无 `llm` 键，`models.providers` 路由 `agentteams-gateway/…`（`deepseek-v4-flash` 主模型 + claude/glm/qwen 别名）→ AI 网关 → `api.deepseek.com/v1` |
| Manager 活动配置 | `D:\AgentTeams\manager-workspace\openclaw.json`（**controller 会重写**：同目录有 `openclaw.json.clobbered.*` 备份） |
| Worker 配置 | controller 从 `worker-openclaw.json.tmpl` 生成（`generator.go`），按需拉起（idle timeout 720min） |
| 插件机制已就位 | openclaw.json 已有 `plugins.entries`（matrix/memory-core/argus-typed-task）+ `load.paths: ["/opt/openclaw/extensions/matrix", …]`——与 LoongSuite 插件目标结构一致 |
| 纯本地 | install-profile `local_only: true`；LLM base_url `https://api.deepseek.com/v1` |
| LoongSuite 插件要求 | 容器内 Node ≥18 + npm + `openclaw` CLI；版本门槛 `hooks.allowConversationAccess` ≥ OpenClaw **2026.4.25** |
| OpenClaw 具体版本 | ✅ 已实测（2026-08-15，一次性 `docker run --entrypoint openclaw` 读镜像）：manager + worker 均为 **OpenClaw 2026.4.14** → **< 2026.4.25 hooks 门槛** |

**选型结论（此前的调研）：** 用 `loongsuite-js` 的 OpenClaw 插件；**不用 Pilot**（宿主侧采集器，OpenClaw on Windows 不在支持表，够不到容器）、**不用 loongsuite-python**（Argus Python 侧 local 引擎无 LLM，没东西可采）、**不用阿里云 AgentLoop**（托管 SaaS，违反 local_only 数据主权）。

## 实测发现（2026-08-15）：AI 网关已内置观测，接点应在网关而非 per-agent

**方向修正**：原计划假设要往每个 OpenClaw agent 装 LoongSuite 插件。实测发现 **AI 网关（Higress，agentteams-controller:8080）本身已经是完整的观测点**：

- 所有 agent（manager + 6 worker）的 LLM 调用都汇聚到 `http://agentteams-controller:8080/v1`（openclaw.json `models.providers.agentteams-gateway`，openai-completions）——**单一 choke point**。
- 网关 8080 listener 已挂 **`ai-proxy` + `ai-statistics-1`（token 统计 wasm）+ `opentelemetry` tracing**，上游是 `llm-deepseek.internal.dns` / `llm-qwen.internal.dns` / `llm-openai-compat.internal.dns`。
- **per-agent token 指标已经存在**：`agentteams-controller:15020/stats/prometheus` 上的 `route_upstream_model_consumer_metric_{input_token,output_token,llm_first_token_duration}{ai_consumer="manager"|"worker-argus-*", ai_model=...}`。实测（2026-08-15，deepseek-v4-flash）：

| ai_consumer | input_tok | output_tok | first_tok_ms |
|---|---|---|---|
| manager | 2,268,724 | 12,268 | 60,934 |
| worker-argus-code | 210,961 | 905 | 1,910 |
| worker-argus-dep | 229,252 | 1,218 | 2,505 |
| worker-argus-sec | 246,348 | 1,095 | 2,544 |
| worker-argus-synth | 212,272 | 1,102 | 2,201 |
| worker-argus-meta | 152,581 | 856 | 1,500 |
| worker-argus-delivery | 184,947 | 1,133 | 1,626 |

- **纯 token 计数**（无 prompt 正文）→ P4 天然成立。
- 网关响应本身带 `usage`（实测单次调用 `prompt_tokens=88, completion_tokens=16`）——usage 未被网关剥掉。
- manager 输入 token 2.27M 占绝对大头、首 token 延迟 60s vs worker ~2s——正是 R4.2 想要的「token 占比/瓶颈」结论。

**修正后的接入路径（替代原 per-agent OpenClaw 插件方案）：**
1. **Token/成本/耗时（R4.2 核心）**：直接 scrape `agentteams-controller:15020/stats/prometheus` 的 `route_upstream_model_consumer_metric_*` → 按 `ai_consumer` 聚合 = 每 agent token 占比/首 token 延迟。**无需装任何插件**。✅ **已落地**：`agentteams/gateway_metrics.py`（`--container agentteams-controller` docker exec 取数 / `--endpoint` 直连，`--json-out` 输出），9 个单测全绿，实测出每 agent token/请求数/平均首 token/服务耗时/输入占比表。
2. **链路（trace）**：网关 OTel tracing 已配但无 collector 端点 → 在 Higress 上设 OTLP collector endpoint（导出到本地 OTLP 后端），拿每次 LLM 调用的 span（consumer/model/耗时）。
3. **LoongSuite 的角色**：作为 OTLP collector + 指标抓取/落盘/可视化的那一环（LoongCollector 可 scrape Prometheus 指标；OTLP trace 后端自托管）。**不是**给 agent 装 instrumentation。

**per-agent OpenClaw 插件的去留**：token/成本已由网关覆盖，不再需要 per-agent 插件。仅当要 **agent 内部的 ReAct/工具调用级 trace**（gateway 看不到的步骤级明细）时才考虑；且要解决 openclaw.json 被 controller clobber 的问题（实测装进去会被 `.clobbered` 回退）——优先级低。Task 1 的 `otel_config.py` 保留，仅服务这条可选路径。

## Global Constraints

- **P4 硬约束**：绝不把 prompt 正文、源码、密钥、私有推理写进 span/观测产物。插件配置必须 `hooks.allowConversationAccess=false`（或不带 hooks 块），让 OpenClaw 安全策略挡住 conversation hooks。
- 观测数据只在**本地**（AI 网关 Prometheus 指标 / 自托管 OTel 后端）；不开外网遥测端点。
- 不破坏 controller 管理的 openclaw.json 工作流：spike 阶段手动改可接受，但 durable 变更要能扛住 controller 重写（走 `generator.go`/template 或启动时 patch）。
- 版本门槛未过（OpenClaw < 2026.4.25）时，插件配置**不得**带 `hooks` 块（低版本会配置校验报错）。
- 不声称观测接入成功，除非：真实 LLM 调用后能从 AI 网关取到每 agent token 计数、后端零 prompt 正文（P4）。
- Docker daemon 当前未起（contract 测试因此失败）——所有 live 任务阻塞，直到 daemon 可用。
- 不在 span/日志/产物里放 API key、Matrix token、密码等凭据。

---

## File Map

### New files（已落地）

- `agentteams/otel_config.py` ✅ — 生成 OpenClaw 插件配置条目（`otel_plugin_entry`/`otel_service_name`），21 单测。**保留仅服务可选 per-agent trace 路径**（Task 7）。
- `agentteams/gateway_metrics.py` ✅ — **替代原 `otel_metrics.py`**：直接 scrape AI 网关 Prometheus 指标 → 按 `ai_consumer` 聚合每 agent token/请求数/平均首 token/服务耗时/输入占比；含 `TokenTotals`/`token_delta`（评测差分用）。9 单测。
- `tests/unit/test_otel_config.py` ✅ / `tests/unit/test_gateway_metrics.py` ✅
- 接入评测门禁 ✅：`demo/eval/harness.py`（`--token-cost` 差分）、`demo/eval/gate.py`（`--max-cost-ratio` 成本预算）、`tests/unit/test_eval_harness.py` / `test_eval_gate.py` 扩展。

### 未做

- `agentteams/otel_metrics.py`（查 Jaeger）— **未建，被 gateway_metrics 替代**。
- durable 化（controller 生成器/镜像）— Task 7 可选。

---

## Task 1: 建可复现的插件配置生成器（本仓库可先动，不依赖 Docker）

**Files:**
- Create: `agentteams/otel_config.py`
- Create: `tests/unit/test_otel_config.py`

**Interfaces:**
- `otel_plugin_entry(endpoint: str, service_name: str, *, version: str | None = None) -> dict` 返回：
  `{"enabled": True, "hooks": {"allowConversationAccess": False}, "config": {"endpoint": ..., "serviceName": ...}}`。
  `version` 解析为 `YYYY.MM.DD` 数值，≥ 20260425 时带 hooks 块；None 或 < 20260425 时省略 hooks 块。
- `otel_service_name(role: str) -> str`：`manager → "argus-manager"`，`dep/code/sec/delivery/meta/synth → "argus-worker-<role>"`。

- [x] **Step 1: 写失败测试**（P4 分支 + 版本分支 + service 命名）
- [x] **Step 2: 实现 `otel_config.py`**，让测试通过
- [x] **Step 3: 跑 `pytest tests/unit/test_otel_config.py` 全绿**（21 passed）

---

## Task 2: 版本与拓扑预检（live gate，需 Docker）

**Files:**
- 无代码改动；记录验证结果到 Task 5 的验证清单。

- [x] **Step 1: `docker ps`**——daemon 已起；agentteams 容器全部 **Exited**（manager/controller/nacos 137，workers 0），未在跑
- [x] **Step 2: 取版本**（`docker run --rm --entrypoint openclaw <img> --version`）：manager + worker 镜像均为 **OpenClaw 2026.4.14**
- [x] **Step 2b: 版本结论**：20260414 **< 20260425** → `otel_config` 走「省略 hooks 块」分支（与 install.sh 对低版本的降级一致）；P4 天然成立（该版本不认 conversation access 字段）；Task 1 设计被实测验证
- [x] **Step 3: 容器内 Node/npm**：manager 内 Node **v22.23.1** / npm **10.9.8**（≥18 ✅）；openclaw 在 `/usr/local/bin/openclaw`
- [x] **Step 4: docker 网络 + AI 网关**：网络 = **`agentteams-net`**；**AI 网关 = `agentteams-controller:8080`（Higress/Envoy 1.36.4）**，所有 agent 的 LLM 都走它 `/v1`（openclaw.json `models.providers.agentteams-gateway`）——这就是「接入 ai 网关」的接点
- [x] **Step 5: 起容器**——manager/controller/nacos/workers 全部拉起并稳定

---

## Task 3: 起本地 OTLP 后端（Jaeger all-in-one）

> ⛔ **未做——已被 AI 网关方案替代。** `docker pull jaegertracing/all-in-one` 被网络（Docker Hub 不可达）挡住；而转向网关后发现 **token/成本主路径根本不依赖 OTel 后端**（ai-statistics 直接出 Prometheus 指标，已由 `gateway_metrics.py` 落地）。Jaeger/OTLP 后端仅在「路径 2：链路 trace」（网关 OTel 加 collector 端点导出 span）时需要，属 AgentTeams 网关配置改动。

- [ ] **Step 1: 起 Jaeger**（挂 agentteams 网络，暴露 UI/OTLP 端口）——未做
- [ ] **Step 2: 容器内可达性**——未做
- [ ] **Step 3: 确认 Jaeger 不暴露到公网**——未做

---

## Task 4: 装插件并落配置（Manager + 一个 Worker）

> ⛔ **试过但放弃——per-agent 路径被 controller clobber 挡死，已被 AI 网关方案替代。** 环境已还原（openclaw.json 恢复、孤立插件目录已删）。

- [x] **Step 1: Manager 装插件**——install.sh 成功（`/root/manager-workspace/.openclaw/extensions/opentelemetry-instrumentation-openclaw`，npm 依赖装好）
- [x] **Step 2: P4 硬化 + 写配置**——用 `otel_config.py` 生成（无 hooks 块）merge 进 openclaw.json + `mc cp` 推 MinIO，**但 10:46:28 被 controller `.clobbered` 回退**（重启即丢）
- [ ] **Step 3: 一个 Worker 落条目**——未做（路径已放弃）
- [x] **Step 4: 重启/生效**——重启了（gateway 新 PID 7）但插件条目被回退，未加载 → 实测结论：**openclaw.json 是 controller 管理的，手动改必被 clobber**（durable 只能改 controller 生成器/镜像，优先级低）

---

## Task 5: 端到端验证（token 可采 + P4 成立）

> ⚠️ **部分——验证改走 AI 网关，不是 OpenClaw 插件 span。** 两个待验证点用网关实测回答：
> - 待验证点 ①（网关是否剥 usage）：**没剥**。网关响应带 `usage`（实测 `prompt_tokens=88, completion_tokens=16`），ai-statistics 指标也有 token 数。
> - 待验证点 ②（无 conversation access 时 token 是否在）：**在，且更彻底**——AI 网关 `ai-statistics` wasm 直接按 `ai_consumer` 计数（纯计数、无正文），无需 OpenClaw 插件的 conversation 钩子。P4 天然成立。

- [x] **Step 1: 真实 LLM 调用过网关**——`curl localhost:18080/v1/chat/completions`（deepseek-v4-flash）HTTP 200、0.9s
- [x] **Step 2: token 断言**——`:15020/stats/prometheus` 的 `route_upstream_model_consumer_metric_*` 按 `ai_consumer` 出每 agent input/output token + `llm_duration_count` + `llm_first_token_duration`（实测表见「实测发现」节）
- [x] **Step 3: P4 断言**——指标是纯 token 计数，无 prompt 正文/源码/密钥
- [x] **Step 4: 记录**——已写入「实测发现」节 + `agentteams/gateway_metrics.py` 聚合器落地
- [ ] **Step 5: agent 内部 ReAct/工具级 trace**（gateway 看不到的步骤级明细）——**未做**，仅当需要时才考虑 per-agent 插件 + 解决 clobber（Task 7）

---

## Task 6: 按 agent 聚合观测数据（R4.2 最小补）

> ✅ **被替代并已落地**：原计划 `otel_metrics.py`（查 Jaeger）→ 实际落地 **`agentteams/gateway_metrics.py`**（直接 scrape AI 网关 Prometheus 指标，更强、无 Jaeger 依赖）。9 个单测全绿，实拉出每 agent token/请求数/平均首 token/服务耗时/输入占比表。**且已接进评测门禁**（R5.2 `--max-cost-ratio` + harness `--token-cost`）。

- [x] **Step 1: 写失败测试**——`tests/unit/test_gateway_metrics.py`（解析/聚合/占比/除零/去噪/差分）
- [x] **Step 2: 实现**——`gateway_metrics.py`（`parse_prometheus`/`aggregate`/`render_table`/`fetch_*`/`TokenTotals`/`token_delta`）
- [x] **Step 3: 对真实 run 输出每 agent 表**——实测 manager 67% input / 1.4s 首 token vs workers ~0.2s
- [x] **Step 4: 接进门禁**——harness `--token-cost` 差分 + gate `--max-cost-ratio` 预算检查（283 单测全绿）

---

## Task 7: durable 化（可选，需 AgentTeams 侧改动）

> ⛔ **未做——仅当需要 agent 内部 ReAct/工具级 trace 才需要。** token/成本主路径已由 AI 网关覆盖（无 clobber 问题），per-agent 插件仅在要步骤级 trace 时才考虑，届时必须改 controller 生成器/镜像（否则 openclaw.json 会被 clobber，Task 4 已实测）。

- [ ] **Step 1: 评估 controller 配置生成**——未做（可选）
- [ ] **Step 2: 或启动时 patch**——未做（可选）
- [ ] **Step 3: Worker 全量**——未做（可选）
- [ ] **Step 4: 回归**——未做（可选）

---

## 验收清单

- [x] Task 2 版本预检记录在案：**OpenClaw 2026.4.14**（< 2026.4.25 hooks 门槛，走无 hooks 分支）
- [x] **AI 网关**（`agentteams-controller:8080`，Higress）确认为唯一 LLM 接点，**自带 `ai-statistics` wasm + OTel tracing**
- [x] 真实 LLM 调用过网关 → **token 可采、P4 成立**（`route_upstream_model_consumer_metric_*` 按 `ai_consumer` 出每 agent 计数，无 prompt 正文）
- [x] **token 聚合落地**：`gateway_metrics.py` 实拉每 agent token/请求数/平均首 token/服务耗时/输入占比表，单测全绿
- [x] **接进评测门禁**：harness `--token-cost` 差分 + gate `--max-cost-ratio` 预算检查，283 单测全绿
- [ ] （可选）agent 内部 ReAct/工具级 trace——需 per-agent 插件 + durable 化（Task 7），优先级低
- [ ] （可选）网关 OTel collector 端点导出链路 span——需 AgentTeams 网关配置改动
- [x] 环境还原：manager openclaw.json 干净、孤立插件目录已删、JSONL 接收器已停、临时 pin 已清
