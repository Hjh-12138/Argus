# Argus v2 初赛方案 PPT 大纲

> 建议 12 页，主线是“AI 代码交付更快，但发布信任链断了；Argus 用 AgentTeams + 可核验证据重建发布门禁”。

## 1. 封面

- 项目名：Argus：AI 代码发布安全门禁
- 一句话：把 AI 生成代码的每次变更，转化为可运行、可验证、可审计的发布决策
- 赛道：Agent Infra
- 当前进展：可运行 PoC + AgentTeams 六 Worker 闭环

## 2. 场景、用户与痛点

- 用户：AI 应用开发团队、平台工程团队、安全与交付负责人
- 场景：AI 生成或大幅修改代码后，准备合并、发布或部署
- 痛点：
  - 依赖幻觉与不存在包
  - 占位实现看似完整
  - 安全漏洞和硬编码密钥
  - CI 有测试但没有执行
  - LLM review 自身可能产生幻觉
- 现状缺口：扫描器给告警，Agent 给结论，但缺少统一证据链与发布门禁

## 3. 产品定位与价值

- 短期切入：变更驱动的 AI 应用发布安全门禁
- 长期方向：广义 AI Agent 安全平台
- 用户获得：
  - 发布前明确的 pass/warn/block/unknown
  - 每条 finding 可回到固定快照、路径、行号与规则版本
  - Agent 失败或证据不足不伪装成功
  - 报告可用于工程修复、复核和审计

## 4. 系统架构

```text
AuditRequest → Preflight → Immutable Snapshot → Scheduler
                                           │
                 dep / code / sec / delivery Workers
                                           │
                                  Meta Evidence Gate
                                           │
                           Synth + Deterministic Policy
                                           │
                       report.json / report.md / exit code

AgentTeams: Project Room + Matrix + MinIO DAG + six Workers + locked Skills
```

- Audit Data Plane 是发布门禁唯一真相源
- Observability 只读，不反向修改 finding 或 policy

## 5. AgentTeams 编排与 Agent 分工

- 六个常驻 Worker：
  - `argus-dep`：依赖声明与 registry 证据
  - `argus-code`：占位实现与代码契约
  - `argus-sec`：静态安全与密钥泄漏
  - `argus-delivery`：CI 与测试执行链
  - `argus-meta`：证据质量门禁
  - `argus-synth`：确定性策略与报告
- 每个 audit 映射为 Project Room
- 四 assessor 并行，Meta 依赖四者，Synth 依赖 Meta
- `REVISION_NEEDED` 创建 revision + Meta recheck；`BLOCKED` 进入 human-wait

## 6. 核心 Skills

- `argus-finding-emit`
- `argus-evidence-verify`
- `argus-release-policy-evaluate`
- `argus-report-materialize`

工程化属性：

- 输入、输出、错误 schema
- 明确禁止条件
- 完整目录 digest lock
- Controller-owned ZIP 分发
- 不运行时拉取 latest
- Worker registry assignment 与文件落盘双重验收

## 7. 数据流与证据链

```text
snapshot_id
  → detector/rule version
  → finding(path, line, source_sha256, evidence)
  → MetaDecision(label, reason_codes)
  → PolicyDecision(release_gate, reasons)
  → immutable report
```

- 源码只在本地静态读取
- Matrix 只发送 task ID、spec 路径和状态
- MinIO 保存类型化 task 工件
- 自然语言 `result.md` 不能替代机器工件

## 8. 三缺陷 Demo

Vulnerable 版本：

1. 不存在依赖 → Dependency finding
2. SQL 字符串拼接 → Security finding
3. CI 未运行已有测试 → Delivery finding
4. 注入虚构文件行号 → Meta 标记 HALLUCINATION 并排除

结果：`release_gate=block`，退出码 `2`。

Fixed 版本：三项缺陷修复，结果 `release_gate=pass`，退出码 `0`。两次 snapshot ID 必须不同，旧报告不覆盖。

## 9. 安全边界与异常分支

- 不执行目标源码、不安装目标依赖、不触发 CI/部署
- 目标仓库文字全部视为不可信数据，防 prompt injection
- 外部查询只允许元数据，源码不出网
- 密钥只保留脱敏值或 HMAC fingerprint
- required Agent 缺失/失败 → unknown，不得 pass
- Skill digest 不匹配 → 分发失败
- Worker/Project/Matrix/MinIO 错误必须显式失败
- trace 禁止源码、原始 prompt/response、private reasoning

## 10. 可观测与评测

初赛 builtin trace：

- allowlist 事件：scheduled、started、finding_emitted、meta_decided、gate_decided、completed、failed 等
- 只允许有界标量 attributes
- forbidden 字段直接丢弃
- JSONL 本地落盘接口

评测不变量：

- vulnerable 100% block
- fixed 100% pass
- Meta 必须拦截 hallucination
- required Agent 不完整不能 pass
- finding path/line/hash/evidence 可复核
- 全量自动化测试与泄漏自检通过

## 11. 开放与复用价值

- Apache-2.0 开源
- 开放 Agent Identity、Skill schema、锁定与分发方法
- 开放三缺陷样例和评测不变量
- 可扩展到架构、性能、鲁棒性 assessor
- 可接入企业 Git、CI/CD、工单、资产与安全系统
- AgentTeams 编排方法可复用于合规、采购、运维等企业任务闭环

## 12. 路线图与当前状态

初赛已完成：

- headless CLI 与确定性门禁
- 六 Worker AgentTeams 编排
- Project Room、Matrix、MinIO task DAG
- 四个锁定核心 Skill
- Meta 幻觉拦截
- 原子 JSON/Markdown 报告
- builtin 结构化 trace recorder
- README、作品简介、PPT 大纲与安全泄漏自检

复赛计划：

- arch/perf/robust assessor
- 增量调度和预算控制
- 完整 OTel/LoongSuite + AgentScope Studio
- 真实结果回传、revision/cancel 审计闭环
- 自动评测、shadow/canary 与 AgentVersion 晋级
