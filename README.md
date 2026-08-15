# Argus v2

**面向 AI 应用开发团队的变更驱动发布安全门禁。** Argus 把一次代码变更映射为可审计的多 Agent 任务，使用确定性规则发现问题、Meta Agent 核验证据、Synth Agent 生成发布结论，并输出可复现的机器报告。

## 为什么做 Argus

AI 生成代码提高了交付速度，也让不存在的依赖、占位实现、SQL 注入和“有测试但 CI 没运行”等问题更容易进入发布链路。普通代码审查工具只给出告警；Argus 固定输入快照、Agent 版本、Skill 与证据链，只有经过 Meta 核验的 finding 才能影响发布门禁。

## 架构

```text
AuditRequest
    │
    ▼
Preflight ──► Immutable Snapshot ──► Heuristic Scheduler
                                        │
                    ┌───────────────────┼────────────────────┐
                    ▼                   ▼                    ▼
             Dependency Agent      Code/Sec Agents      Delivery Agent
             (dep)            (code: 占位+可维护性    (delivery)
                               sec: 静态安全)
                    └───────────────────┼────────────────────┘
                                        ▼
                                  Meta Evidence Gate
                                        ▼
                              Synth + Deterministic Policy
                                        ▼
                          report.json / report.md / exit code
                                        ▼
                        demo/eval 评测集 + harness/gate 门禁（R0.4/R5.1/R5.2）

AgentTeams control plane
Project Room ── 6 Workers ── locked Skills ── Nacos 配置中心 + MinIO task DAG
```

**架构分层**——确定性形式层（已实现）+ 语义判断层（LLM）+ 机器强约束层（贯穿全程）：

| 层 | 职责 | 状态 |
|---|---|---|
| **确定性形式层** | 不可变快照 + hash、确定性规则（含 11 条可维护性规则）、严格 schema、digest 引用、幂等键 + CAS、确定性 Meta 引用核验、确定性 policy | ✅ 已实现 |
| **语义判断层** | `--engine agentteams` 下 Manager/Worker 为 LLM agent（OpenClaw），读源码做语义分析、证据研判、跨 agent 一致性判断；skill 侧 `_shared/llm_review.py` 对确定性 finding 做 LLM 深度复核（抑制 FP / 确认）。语义幻觉的独立核验为路线图 R1.2（未实现） | ⚠️ 部分实现 |
| **机器强约束层** | P1 机器强约束优先于约定 · P2 生成与校验分离（LLM 自由生成、出不了机器闸门）· P3 fail-closed 单向保守 · P4 元数据与原文分离 · P5 独立验证不可自评 | ⚠️ 部分实现 |

机器强约束（P1-P5）落地现状：P2/P3/P4 已实现——LLM/规则生成 finding → 确定性 Meta 核验 → fail-closed policy（缺 required agent 即 `unknown`），观测/报告只记元数据 + 脱敏 + HMAC；P1/P5 部分——DAG 校验器、字段级 ACL、语义幻觉独立核验在路线图 R0-R2（待落地），评测 ground truth 已人标注、独立于 Meta（P5 在评测层成立）。

机器强约束（核心不变量，贯穿全程）：

- **[P1/P2]** 启发式调度先于模型，不允许模型删掉必需安全检查（`MANDATORY_AGENTS`）。
- **[确定性形式]** 所有 Agent 使用同一个不可变源码快照。
- **[P4]** finding 必须携带 path、line、source hash 和可复核 evidence。
- **[P2/P5]** Meta 只核验证据，不创造 finding，也不决定 release gate。
- **[P3]** required Agent 缺失或失败时不能伪装成功（fail-closed，gate 置 `unknown`）。
- **[P4]** 源码、密钥、原始 prompt/response 和私有推理不进入 Matrix、trace 或报告。

**可维护性审查**（`code` agent，2026-08 新增）：11 条确定性规则（CODE-101..CODE-111）覆盖长函数/过多参数/单字母参数/深层嵌套/多布尔互斥/魔法数字/裸字符串枚举/映射 if 链/OR 链/平行数组/线性查找缺索引。规则引擎为纯 stdlib 模块，由本地 `CodeDetector` 与 AgentTeams skill `argus-code-maintainability-scan` 共享，parity 测试保证两侧一致；严重度为 low/medium，只产生 warn、永不 block 发布。

## 快速开始

### 1. 环境

- Python 3.11+
- Docker Desktop
- AgentTeams v1.2.0-beta.1（依赖 Nacos 3.2+，作为 Skill 配置中心）
- 本地开发测试：`pytest>=8.0`

```bash
python -m pip install -e ".[dev]"
```

### 2. 启动并验证 AgentTeams

启动 Docker Desktop 和 AgentTeams 后，在当前验证环境运行：

```powershell
& "D:\AgentTeams\install\verify-agentteams.ps1"
docker ps --format '{{.Names}} {{.Status}}'
docker exec agentteams-manager hiclaw get workers -o json
```

预期 `agentteams-controller`、`agentteams-manager` 与六个 Argus Worker 均处于 Running。

**Nacos 依赖**：AgentTeams 栈内自带 Nacos 3.2+，作为 Skill 配置中心。Argus 侧：

- `skills/publish_nacos.py` 把锁定 Skill 发布到 Nacos（默认 `nacos://nacos:8848/public`，`--verify-only` 校验，`--publish` 发布）。
- `agentteams/apply_worker_config.py` 按 `skills/skills.lock.json` 的 assignments 把 Skill 同步到各 Worker。
- `skills/skills.lock.json` 固定 Nacos 发布源 + 完整 Skill 目录 digest；运行时分发禁止拉取 `latest`。

Skill 发生变化后重发：

```bash
python skills/publish_nacos.py --version <锁内版本> --publish   # 默认连 127.0.0.1:8848 / namespace public
python -m agentteams.apply_worker_config --workspace .          # 按锁内 assignments 同步到 Worker
```

### 3. 运行三缺陷 Demo

```bash
argus audit \
  --target demo/scenarios/ai-pr-three-defects/vulnerable \
  --headless \
  --registry-fixture demo/scenarios/ai-pr-three-defects/registry-fixture.json
```

预期退出码为 `2`，release gate 为 `block`。输出位于：

```text
.argus/reports/report.json
.argus/reports/report.md
.argus/state.db
```

运行修复版本：

```bash
argus audit \
  --target demo/scenarios/ai-pr-three-defects/fixed \
  --headless \
  --registry-fixture demo/scenarios/ai-pr-three-defects/registry-fixture.json
```

预期退出码为 `0`，release gate 为 `pass`。

## 三缺陷 Demo

| 缺陷 | Agent | 可复核证据 |
|---|---|---|
| 不存在的依赖包 | `argus-dep` | manifest 行号、registry fixture、source hash |
| SQL 字符串拼接注入 | `argus-sec` | 查询代码行、规则版本、脱敏上下文 |
| CI 只编译、不运行已有测试 | `argus-delivery` | workflow 与测试文件的交叉证据 |

Demo 可额外注入一个引用不存在路径的 finding，用于证明 Meta 会将其标记为 `HALLUCINATION` 并从主报告排除。

## Agent Identity

| Worker | 职责 | 初赛状态 |
|---|---|---|
| `argus-dep` | 依赖声明与 registry 证据审计 | Running |
| `argus-code` | 占位实现 + 可维护性审查（11 条确定性规则） | Running |
| `argus-sec` | 静态安全证据与密钥泄漏检查 | Running |
| `argus-delivery` | CI、测试覆盖与交付链审计 | Running |
| `argus-meta` | finding 证据质量门禁 | Running |
| `argus-synth` | 确定性策略与报告物化 | Running |

AgentTeams 负责 Worker 生命周期、Project Room、Matrix dispatch、Nacos Skill 分发和 MinIO task DAG；Argus 负责类型化任务、证据验证和确定性发布策略。

## 核心 Skills

| Skill | 使用者 | 作用 |
|---|---|---|
| `argus-finding-emit` | dep/code/sec/delivery | 生成符合 schema 的 finding 与 evidence |
| `argus-code-rule-scan` | code | 占位实现检测（CODE-001） |
| `argus-code-maintainability-scan` | code | 可维护性审查（CODE-101..CODE-111，11 条规则） |
| `argus-evidence-verify` | meta | 核验路径、行号、快照 hash 与证据一致性 |
| `argus-release-policy-evaluate` | synth | 根据 VERIFIED finding 计算 pass/warn/block/unknown |
| `argus-report-materialize` | synth | 原子生成 JSON 与 Markdown 报告 |

`skills/skills.lock.json` 固定 Nacos 发布源 + 完整 Skill 目录 digest。分发前校验 digest，禁止运行时拉取 `latest`。

## 安全边界

- 目标仓库的 README、注释、prompt、Skill 和构建脚本一律视为不可信数据。
- 默认只进行静态读取，不安装目标依赖、不执行目标源码、不触发 CI 或部署。
- 网络 MCP 仅允许元数据查询；源码不发送给外部模型或工具。
- 报告中的目标路径被本地化处理，密钥使用脱敏值或 HMAC fingerprint。
- trace 只记录 allowlist 结构化事件，不记录源码、原始 prompt/response 或私有推理。
- AgentTeams Skill 使用 Controller-owned ZIP 路径分发，完整目录 digest 必须匹配 lock。

## 测试

默认测试不创建新的 AgentTeams Project：

```bash
python -m pytest tests/ -v
```

真实 AgentTeams 用例使用 `agentteams` marker，并要求 Docker 环境。执行 live E2E 会创建 Project Room 和 MinIO 工件，应只在明确授权的验收环境运行。

## 当前进展

初赛核心链路已完成：本地 headless 三缺陷 Demo、六 Worker AgentTeams 编排、Nacos 锁定 Skill 分发、Project Room、MinIO task DAG、Meta 幻觉拦截、确定性 release gate、原子报告和 builtin 结构化 trace recorder。

已补的工程能力：

- **代码可维护性审查**：`code` agent 新增 11 条确定性规则（CODE-101..CODE-111），本地引擎与 AgentTeams skill 共享同一纯 stdlib 规则引擎，parity 测试保证两侧一致。
- **评测门禁**：`demo/eval/` 评测集（9 场景：simple/complex/abnormal）+ `harness.py`（R5.1，语义键对齐算 recall/precision/gate 一致性）+ `gate.py`（R5.2，`eval.lock.json` 版本 pin、逐场景不回归、可选 token 成本预算）。
- **观测**：AI 网关（`agentteams-controller:8080`，Higress）按 `ai_consumer` 输出每 agent token/耗时指标，`agentteams/gateway_metrics.py` 聚合；`--token-cost` 已接入评测门禁成本维度。

## License

Apache-2.0。第三方系统、模型、容器和数据集遵循各自许可证与服务条款；闭源模型和商业 API 不随本仓库再分发。
