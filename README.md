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
                    └───────────────────┼────────────────────┘
                                        ▼
                                  Meta Evidence Gate
                                        ▼
                              Synth + Deterministic Policy
                                        ▼
                          report.json / report.md / exit code

AgentTeams control plane
Project Room ── six Workers ── locked Skills ── MinIO task DAG
```

核心不变量：

- 启发式调度先于模型，不允许模型删掉必需安全检查。
- 所有 Agent 使用同一个不可变源码快照。
- finding 必须携带 path、line、source hash 和可复核 evidence。
- Meta 只核验证据，不创造 finding，也不决定 release gate。
- required Agent 缺失或失败时不能伪装成功。
- 源码、密钥、原始 prompt/response 和私有推理不进入 Matrix、trace 或报告。

## 快速开始

### 1. 环境

- Python 3.11+
- Docker Desktop
- AgentTeams v1.2.0-beta.1
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
| `argus-code` | 占位实现与代码契约审计 | Running |
| `argus-sec` | 静态安全证据与密钥泄漏检查 | Running |
| `argus-delivery` | CI、测试覆盖与交付链审计 | Running |
| `argus-meta` | finding 证据质量门禁 | Running |
| `argus-synth` | 确定性策略与报告物化 | Running |

AgentTeams 负责 Worker 生命周期、Project Room、Matrix dispatch 和 MinIO task DAG；Argus 负责类型化任务、证据验证和确定性发布策略。

## 核心 Skills

| Skill | 使用者 | 作用 |
|---|---|---|
| `argus-finding-emit` | dep/code/sec/delivery | 生成符合 schema 的 finding 与 evidence |
| `argus-evidence-verify` | meta | 核验路径、行号、快照 hash 与证据一致性 |
| `argus-release-policy-evaluate` | synth | 根据 VERIFIED finding 计算 pass/warn/block/unknown |
| `argus-report-materialize` | synth | 原子生成 JSON 与 Markdown 报告 |

`skills/skills.lock.json` 固定完整 Skill 目录 digest。分发前校验 digest，禁止运行时拉取 `latest`。

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

初赛核心链路已完成：本地 headless 三缺陷 Demo、六 Worker AgentTeams 编排、锁定 Skill 分发、Project Room、MinIO task DAG、Meta 幻觉拦截、确定性 release gate、原子报告和 builtin 结构化 trace recorder。

## License

Apache-2.0。第三方系统、模型、容器和数据集遵循各自许可证与服务条款；闭源模型和商业 API 不随本仓库再分发。
