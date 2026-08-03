# Argus-on-AgentTeams 一阶段闭环补齐设计

**日期：** 2026-08-03  
**状态：** 已批准，待实施  
**目标：** 补齐一阶段验收中的四个缺口，使 Argus 的真实审计角色运行在 AgentTeams Worker 中，并以 `E:\heishou\koubo` 当前源码工作区作为真实任务目标重新完成八项验收。

---

## 1. 定位与边界

### 1.1 系统定位

AgentTeams 是通用多 Agent 执行与协作引擎，负责 Worker 生命周期、容器运行、Matrix 通信、Project Room、任务投递、MinIO 工件和 Skill 物化。

Argus 是构建在 AgentTeams 上的 AI 代码发布安全门禁，负责不可变快照、审计 Agent、Finding/Evidence/Meta/Policy schema、确定性门禁、报告和验收规则。

```text
Argus 业务层
  ├─ AuditRequest / SourceSnapshot
  ├─ dep / code / sec / delivery / meta / synth
  ├─ Finding / MetaDecision / PolicyDecision
  └─ report.json / report.md / stable exit code
             │
             ▼
AgentTeams 执行层
  ├─ Manager / Controller / Worker
  ├─ Matrix Project Room
  ├─ Task dispatch / ACK / state
  ├─ MinIO typed artifacts
  └─ custom Skill materialization
```

Argus 和 AgentTeams 不合并为一个业务框架。AgentTeams 的改动必须保持通用、最小、可上游化，不能写死 Argus 的 Finding、审计类别或发布策略。

### 1.2 实施范围

实施允许同时修改：

1. `E:\heishou\Argus v2`；
2. `E:\heishou\AgentTeams-v1.2.0-beta.1` 的本地 fork。

AgentTeams 以 upstream `v1.2.0-beta.1` 为基线，只添加：

- custom Skill 权威同步；
- expected/observed digest 校验；
- 通用 Task 注册、派发、ACK 和终态原语；
- Worker 的幂等任务执行接口。

不在本阶段实现完整 Project/Task CRD 平台、通用工作流语言、Watcher、RAG、Matrix UI 或完整飞轮。

### 1.3 真实目标边界

真实任务目标固定为：

```text
E:\heishou\koubo
```

该仓库仅作为只读审计输入。Argus 不得：

- 修改、删除、清理、暂存或提交目标文件；
- 安装目标依赖；
- 执行目标源码；
- 启动目标服务；
- 触发目标 CI 或部署；
- 将 synthetic-secret canary 写入目标工作区。

---

## 2. 当前缺口与根因

一阶段当前有四个未满足项：

1. 真实 AgentTeams Worker 没有产出 `result.md` 和机器工件，Project 停留在 `active`；
2. `HALLUCINATION → REVISION_NEEDED → revision → Meta recheck → Synth` 只有本地逻辑和 mock 测试，没有真实 Worker 闭环；
3. 只有 4 个唯一锁定 Skill，低于“至少 6 个”的正式标准；
4. 泄漏检查只覆盖本地 report/trace 和有限 shared 工件，没有随机 canary 穿过 Matrix、Worker、MinIO、日志、trace 和 SQLite 的全链路证据。

四个缺口的共同根因是：当前 AgentTeams 集成完成了控制面初始化，却没有形成真实执行面。

```text
当前：Project/Room/DAG/spec 创建 → Matrix 通知 → 停止
目标：注册 → 派发 → ACK → Worker Skill → typed result → ingest → unlock/revision → completed
```

---

## 3. 方案选择

### 3.1 采用方案

采用“最小上游化 AgentTeams 补丁 + Argus-on-AgentTeams 真实执行集成”。

- AgentTeams 增加通用 custom Skill 权威同步和 Task 原语；
- Argus 增加自包含审计 Skill、Project Driver、reconciler 和验收器；
- Worker 由 Matrix 完整 mention 唤醒，并调用锁定的确定性 Skill；
- 模型负责理解任务和调用 Skill，不负责发明审计结论；
- MinIO typed artifacts 是机器事实源，Matrix 只是唤醒和协作通道。

### 3.2 未采用方案

#### 仅在 Argus 中 `docker exec` Worker

该方案稳定但绕过 AgentTeams 任务语义，不能证明 Matrix/Worker 协作闭环，也会把安装细节写死进 Argus。

#### 由模型自主生成全部审计结论

该方案不确定性和泄漏面过大，无法保证 finding fingerprint、Meta 判定和 release gate 的可重复性。

#### 完整重构 AgentTeams 资源模型

新增通用 Skill/Project/Task CRD 全生命周期超出一阶段最小补缺范围。

---

## 4. 自定义 Skill 权威分发

### 4.1 保持现有语义

`WorkerSpec.Skills` 和 `hiclaw --skills` 继续只表示 AgentTeams 内置 Skill 名称分配，不承担任意本地目录上传。

自定义 Skill 使用 Worker package manifest v2 的 `managed_artifacts` 字段。

### 4.2 Package manifest v2

```json
{
  "type": "worker",
  "version": 2,
  "worker": {
    "suggested_name": "argus-sec",
    "model": "<locked-model>",
    "runtime": "openclaw"
  },
  "managed_artifacts": [
    {
      "path": "skills/argus-secret-scan",
      "mode": "authoritative",
      "digest": "sha256:<directory-digest>"
    },
    {
      "path": "skills/argus-finding-emit",
      "mode": "authoritative",
      "digest": "sha256:<directory-digest>"
    }
  ]
}
```

### 4.3 权威同步语义

对于 `mode=authoritative`：

1. 路径必须位于安全白名单中，首期仅允许 `skills/<safe-name>/`；
2. ZIP 内文件清单必须与声明目录一致；
3. Controller 计算目录 expected digest；
4. 内容先写入同一存储后端的临时前缀；
5. 临时前缀 digest 校验通过后覆盖目标目录；
6. 目标目录中 manifest 未声明的旧文件必须清理；
7. manifest 未管理的 Worker 文件不得修改；
8. Worker 同步后计算 observed digest；
9. expected digest 与 observed digest 一致后 Worker 才进入 Skill-ready；
10. 任一步失败时保留旧的完整可用版本，禁止半更新。

旧 manifest 或无 `managed_artifacts` 的 package 保持 beta.1 原有 seed-only 行为，以维持向后兼容。

### 4.4 为什么不使用常规 `--skills`

固定 AgentTeams beta.1 的 `--skills` 只写入内置 Skill 名称，不上传自定义目录。Argus Skill 包含 `SKILL.md`、manifest、schema 和 Python 实现，因此需要 Controller-mediated package 路径。

现有 ZIP 路径只能用于首次 seed：已有文件不覆盖、删除文件不清理。Package v2 的权威同步补丁用于修复更新收敛问题，而不是改变内置 `--skills` 的语义。

### 4.5 版本锁

`agentteams/contract.lock.json` 必须记录并验证：

- upstream tag；
- upstream commit SHA；
- fork commit SHA；
- patch-set digest；
- Controller image digest；
- Manager image digest；
- Worker image digest；
- package manifest schema version；
- task protocol schema version。

验收报告必须明确写为“基于 AgentTeams v1.2.0-beta.1 的固定 fork”，不得将其描述为未经修改的 upstream beta.1。

---

## 5. Argus Skill 集合

### 5.1 唯一 Skill 数量

保留现有 4 个 Skill：

1. `argus-finding-emit`；
2. `argus-evidence-verify`；
3. `argus-release-policy-evaluate`；
4. `argus-report-materialize`。

新增 4 个角色执行 Skill：

5. `argus-dependency-inspect`；
6. `argus-code-rule-scan`；
7. `argus-secret-scan`；
8. `argus-ci-policy-check`。

最终为 8 个唯一锁定 Skill，超过初赛至少 6 个的要求。

### 5.2 Worker 分配

```text
argus-dep
  ├─ argus-dependency-inspect
  └─ argus-finding-emit

argus-code
  ├─ argus-code-rule-scan
  └─ argus-finding-emit

argus-sec
  ├─ argus-secret-scan
  └─ argus-finding-emit

argus-delivery
  ├─ argus-ci-policy-check
  └─ argus-finding-emit

argus-meta
  └─ argus-evidence-verify

argus-synth
  ├─ argus-release-policy-evaluate
  └─ argus-report-materialize
```

### 5.3 Skill 自包含契约

每个 Skill 必须：

- 包含 `SKILL.md`、`manifest.yaml`；
- 包含 input/output/error JSON schema；
- 提供稳定的 JSON/file artifact 入口；
- 不依赖宿主机中未打包的 `core.*` 或 `agents.*`；
- 在只有 Worker runtime、Skill 目录和声明输入时可执行；
- 不安装目标依赖，不执行目标源码；
- 输出匹配对应机器 schema；
- 通过 schema、contract、unit 和 security 测试；
- Worker 目标目录回读 digest 与 `skills.lock.json` 一致。

---

## 6. AgentTeams 通用 Task 协议

### 6.1 状态机

```text
REGISTERED
    ↓
DISPATCHED
    ↓
ACKNOWLEDGED
    ↓
RUNNING
    ├─→ COMPLETED
    ├─→ REVISION_NEEDED
    ├─→ BLOCKED
    ├─→ FAILED
    ├─→ TIMED_OUT
    └─→ CONFLICT
```

状态只能向前转换。每次状态写入使用 compare-and-set revision，禁止覆盖更新和状态倒退。

### 6.2 Task 工件布局

```text
tasks/<task-id>/
├── meta.json
├── spec.md
├── base/
│   ├── request.json
│   ├── snapshot-ref.json
│   ├── agent-version.json
│   └── upstream-artifacts.json
├── dispatch/
│   ├── envelope.json
│   └── ack.json
├── artifacts/
│   └── <typed-result>.json
├── result.md
└── events.jsonl
```

`dispatch/envelope.json` 至少包含：

- task ID；
- project ID；
- assigned Worker；
- task kind；
- Skill 名称和 digest；
- 输入工件 digest；
- attempt；
- deadline；
- idempotency key；
- 输出 schema 路径。

### 6.3 权威事实源

- Matrix 消息负责唤醒、通知和人类可见协作；
- MinIO task state 和 typed artifacts 是机器事实源；
- `result.md` 是人类摘要，不得替代机器工件；
- Argus Project Driver 必须再次验证 schema、snapshot、agent、Skill digest 和 upstream artifact digest。

### 6.4 可靠派发与 ACK

1. Argus Driver 注册 Task；
2. AgentTeams 写入 envelope；
3. Project Room 完整 mention 对应 Worker；
4. Worker 读取并验证 envelope；
5. Worker 写 `ack.json`；
6. Worker 调用锁定 Skill；
7. Worker 写机器工件、`result.md` 和终态事件；
8. Argus Driver ingest 结果并解锁下游。

默认：

```text
ack_timeout = 60s
run_timeout = 300s
```

ACK 超时只允许使用同一 attempt 和 idempotency key 重发一次。第二次仍无 ACK 时 Task 进入 `TIMED_OUT`。

---

## 7. Argus Project Driver

### 7.1 初始 DAG

```text
dep ─────┐
code ────┼─→ meta → synth
sec ─────┤
delivery ┘
```

四个 assessor 必须分别由真实 Worker 执行，并生成真实 `AgentResult` 和 `result.md`。

Meta Worker 读取同一 snapshot 的四个 assessor 机器工件，输出 `meta-decisions.json`。

Synth Worker 只在 Meta 或 Meta recheck 完成后运行，输出 `policy-decision.json`、`report.json` 和 `report.md`。

### 7.2 Headless 引擎

正式入口：

```bash
argus audit --headless
```

默认使用 AgentTeams 执行引擎。报告必须记录：

```json
{
  "execution_engine": "agentteams"
}
```

保留显式离线开发模式：

```bash
argus audit --headless --engine local
```

本地模式报告记录 `execution_engine=local`，不得作为一阶段真实 AgentTeams 闭环证据。

### 7.3 Driver 恢复能力

Project Driver 必须能够：

- 从 MinIO `meta.json` 和 `events.jsonl` 恢复；
- ingest 已完成但尚未处理的结果；
- 幂等解锁下游；
- 检测同一 idempotency key 的结果冲突；
- required task 失败时进入 `human-wait`；
- 只有全部 required tasks 完成后将 Project 标记为 `completed`。

---

## 8. 真实 Hallucination 与 Revision

### 8.1 验收 Probe

不得修改 `koubo` 来制造幻觉。验收 profile 使用 Controller-owned instruction：

```json
{
  "acceptance_probe": {
    "type": "invalid_finding",
    "agent": "code",
    "file": "__argus_acceptance__/missing.py",
    "line": 88
  }
}
```

该字段只允许在显式 acceptance profile 中使用；普通生产审计必须拒绝该字段。

Code Worker 先执行真实 `koubo` 审计，再额外输出一条标记为 acceptance probe 的无效 Finding。

### 8.2 Revision DAG

```text
code original
    ↓
meta: HALLUCINATION + REVISION_NEEDED
    ↓
code-revision-1
    ↓
meta-recheck-1
    ↓
synth
```

规则：

- Meta 工件必须包含被拒 Finding ID、`HALLUCINATION`、reason code 和 `revision_for`；
- revision task 输入包含公开 reason code，不包含私有推理；
- Synth 依赖立即替换为 Meta recheck；
- revision/recheck 完成前 Synth 保持 `pending`；
- recheck 成功后原 Meta task 标记 `REVISION_RESOLVED`；
- 最终报告记录一次 hallucination 质量计数，但主 Findings 不含 probe；
- Project 最终达到 `completed`。

每个原始 Task 最多允许 2 次 revision。第二次 recheck 仍要求 revision 时 Project 进入 `human-wait`。

---

## 9. `koubo` 当前源码工作区快照

### 9.1 纳入范围

- Git tracked 文件的当前内容；
- 已修改但未提交的源码、配置和测试；
- 新增且属于源码树的文件；
- 删除状态记录；
- 每个文件的相对路径、大小、SHA-256 和语言。

### 9.2 排除范围

默认排除：

```text
.git/
node_modules/
__pycache__/
.pytest_cache/
.pytest-tmp-*/
*.pyc
.edge-diagnostic-profile*/
.web-test-data/
tmp-*/
tmp-video-*/
dist/
build/
coverage/
```

默认排除生成媒体，如 `*.png`、`*.mp4`，除非使用显式 allowlist 纳入。

Preflight 必须输出 include/exclude manifest 和逐项原因。审计开始后快照不可变，目标后续变更进入下一次 run。

### 9.3 真实任务通过语义

`koubo` 的 release gate 可以是 `pass`、`warn`、`block` 或 `unknown`。A4 验收验证的是：

- 真实 Worker 完成；
- Finding 可复核；
- required task 无缺失；
- 最终 gate 与 Finding 和 task 状态一致；
- Project completed。

验收不得预设或强迫目标仓库得到 pass。

---

## 10. 全链路泄漏验收

### 10.1 独立 Canary Project

Synthetic-secret 不写入 `koubo`。验收器创建独立临时 fixture 和每次运行唯一的随机 canary，并运行第二个真实 AgentTeams Project。

Canary 仅允许存在于受限输入 fixture；不得出现在任何输出、通信或观测表面。

### 10.2 必查表面

1. Project Room Matrix 事件；
2. Worker Room Matrix 事件；
3. Manager/admin 通知；
4. MinIO Project/task spec、result、机器工件和报告；
5. Worker task history、progress 和相关 memory 文件；
6. 六个 Worker 容器日志；
7. Manager 和 Controller 日志；
8. Argus CLI stdout/stderr；
9. report JSON/Markdown；
10. trace JSONL；
11. SQLite 文本字段；
12. 异常和错误消息。

### 10.3 通过条件

- Security Worker 产生 secret Finding；
- Finding 只包含脱敏值或 salted HMAC fingerprint；
- Matrix raw canary 命中数为 0；
- MinIO raw canary 命中数为 0；
- 日志 raw canary 命中数为 0；
- Worker FS 非许可位置命中数为 0；
- report/trace/SQLite/stdout/stderr 命中数为 0；
- `private_reasoning`、`reasoning_text`、`raw_prompt`、`raw_response`、`source_code` 均不得出现。

### 10.4 共享 Sanitizer

实现一个确定性递归 sanitizer，处理：

- dict key；
- dict value；
- list/tuple；
- 普通字符串中嵌入的 secret；
- 异常文本；
- bounded scalar trace attributes。

Sanitizer 必须用于：

- Matrix send；
- MinIO publish；
- Worker result/progress publish；
- report materialization；
- trace attributes；
- CLI/log/error wrapping。

不得只依赖危险字段名过滤。

### 10.5 日志安全

验收器禁止保存完整 `docker inspect`。只允许收集容器名、状态和镜像 digest 等 allowlist 元数据。

日志在本地流式扫描，只输出脱敏命中摘要。发现真实凭据模式时立即失败，但原始值不得进入 acceptance report。

---

## 11. 幂等、错误与冲突

### 11.1 幂等键

```text
sha256(
  project_id
  + task_id
  + attempt
  + input_artifact_digest
  + skill_digest
  + agent_version
)
```

同一幂等键：

- 重复 Matrix 消息只重复 ACK，不重复执行；
- 重复 result 提交必须字节一致；
- 不同结果 digest 触发 `CONFLICT`；
- `CONFLICT` 使 Project 进入 `human-wait`。

### 11.2 失败语义

- required task 的 `FAILED/BLOCKED/TIMED_OUT/CONFLICT` 不得产生 pass；
- Project Driver 将 gate 置为 `unknown`；
- 退出码由 `policy.incomplete_run` 映射；
- 模型 429、超时或拒绝不得解释为“未发现问题”；
- Worker 已 ACK 后超时，不启动并发 duplicate attempt；先发送 cancel 标记并进入 `human-wait`。

---

## 12. 资源保留与清理

验收资源 ID：

```text
argus-accept-<UTC timestamp>-<random suffix>
```

规则：

- 本地临时 fixture、快照和报告可由验收器清理；
- Project Room 和 MinIO 工件默认保留 24 小时供复核；
- 提供 `argus acceptance cleanup --run-id <id>`；
- 清理命令只删除 evidence manifest 精确列出的资源；
- 禁止使用宽泛前缀递归删除；
- 失败时保留 sanitized evidence bundle；
- `koubo` 永不进入清理清单；
- 六个长期 Worker 不因单次验收删除。

---

## 13. 统一一阶段验收命令

```powershell
argus acceptance phase-one `
  --target "E:\heishou\koubo" `
  --workspace-mode current-source `
  --agentteams-live `
  --acceptance-probe hallucination-revision `
  --leakage-e2e
```

输出：

```text
.argus/acceptance/<run-id>/
├── acceptance.json
├── acceptance.md
├── evidence-manifest.json
├── command-results/
└── sanitized-excerpts/
```

---

## 14. 八项验收矩阵

### A1 Vulnerable Demo

- 使用内置 vulnerable fixture；
- exit code 2；
- gate=block；
- 生成 JSON/Markdown；
- 检出 dependency.nonexistent、security.sql_injection、delivery.test_gap。

### A2 真实 Hallucination 与 Revision

- 使用 `koubo` 冻结快照和 acceptance probe；
- Code Worker 输出 probe Finding；
- 真实 Meta 工件判定 HALLUCINATION 并给出 revision target；
- MinIO 中创建真实 revision 和 recheck task；
- Code Worker 真实提交修订结果；
- Meta Worker 真实完成 recheck；
- Synth 在 recheck 前保持 pending；
- 主报告排除 probe；
- Project completed。

### A3 Fixed Demo

- 使用内置 fixed fixture；
- 新 snapshot；
- exit code 0；
- gate=pass；
- vulnerable 的三个稳定 fingerprint 消失。

### A4 AgentTeams 真实闭环

- 目标为 `E:\heishou\koubo` 当前源码工作区；
- Project Room 存在；
- 六 Worker 有真实 ACK；
- 四 assessor 有机器工件和 result.md；
- Meta 有机器工件和 result.md；
- Synth 有 policy、report 和 result.md；
- MinIO DAG 完整；
- execution_engine=agentteams；
- Project completed；
- 实际 gate 与真实 Finding 和 task 状态一致。

### A5 Skill 契约

- 唯一 locked Skill 数量至少 6，目标为 8；
- 每个 Skill 结构、schema、unit、contract 和 security 测试通过；
- 每个 Skill 自包含执行通过；
- Worker assignment 与 Identity 一致；
- package expected digest 等于 Worker observed digest；
- overwrite、delete 和 stale-file prune 回归测试通过。

### A6 统一测试

- Argus 默认测试全部通过；
- AgentTeams fork 单元和集成测试全部通过；
- Argus live AgentTeams E2E 全部通过；
- 最终报告分别记录 suite 数量、通过数、失败数和跳过数；
- 不用简单相加掩盖重复收集。

### A7 全链路泄漏

- 使用独立随机 canary fixture；
- Security Finding 存在且已脱敏/HMAC；
- Matrix、MinIO、logs、Worker FS、report、trace、SQLite、stdout/stderr raw canary 均为 0；
- 私有字段命中为 0。

### A8 交付材料

- README 规定章节齐全；
- 作品简介不超过 500 字；
- PPT 大纲章节完整；
- 文档中的 Worker、Skill 数量和执行路径与实测一致；
- 文档不宣称未经验证的能力；
- `acceptance.md` 可作为初赛技术验收附件。

总门禁：

```text
8/8 PASS  → phase_one=accepted
任一 FAIL → phase_one=rejected
任一 BLOCKED → phase_one 不能 accepted
```

---

## 15. 预计代码边界

### 15.1 AgentTeams fork

主要修改：

```text
hiclaw-controller/
├── package manifest v2
├── managed_artifacts authoritative sync
├── expected/observed digest
├── task register/dispatch/ack/status API
├── fork/version reporting
└── unit/integration tests

worker/
├── task envelope listener
├── Skill digest verification
├── idempotent executor
├── result/event publisher
└── tests
```

### 15.2 Argus

主要修改：

```text
agentteams/
├── custom Skill/task API wrapper
├── ProjectDriver
├── reconciler
├── target snapshot packager
└── acceptance evidence collector

skills/
├── 4 个现有 Skill 自包含化
└── 4 个新增角色 Skill

cli/
├── 默认 AgentTeams engine
├── 显式 --engine local
├── acceptance phase-one
└── acceptance cleanup

tests/
├── real Worker E2E
├── real revision E2E
├── Skill authoritative sync
├── random-canary leakage E2E
└── acceptance report contracts
```

`E:\heishou\koubo` 不在修改范围内。

---

## 16. 实施顺序

1. 为 AgentTeams fork 增加 package v2 和权威 Skill 同步；
2. 增加 Task 协议、Worker ACK 和幂等执行；
3. 在 Argus 中实现 8 个自包含 Skill 与锁文件；
4. 实现 Argus Project Driver 和真实 assessor DAG；
5. 实现真实 Meta revision/recheck/Synth；
6. 实现 `koubo` 当前源码工作区快照；
7. 实现共享 sanitizer 和随机 canary 全链路验收；
8. 实现统一 phase-one acceptance 命令；
9. 更新 README、简介和 PPT；
10. 运行八项验收并生成 evidence bundle。

每一步必须保留可验证边界，不能用 mock 结果代替真实 Worker 证据。

---

## 17. 完成定义

本设计仅在以下条件全部满足时完成：

- AgentTeams fork 版本和镜像可复现；
- 8 个 Skill 在真实 Worker 中与 lock digest 一致；
- `koubo` 只读真实审计 Project 达到 completed；
- Hallucination revision/recheck/Synth 在真实 Worker 中完成；
- 随机 canary 全链路零泄漏；
- 八项验收全部 PASS；
- 生成完整、脱敏、可复核的 acceptance evidence bundle。
