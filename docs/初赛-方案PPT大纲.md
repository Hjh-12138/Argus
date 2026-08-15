# Argus v2 初赛方案 PPT 大纲

> 建议 15 页，主线：**“AI 代码交付更快，但发布信任链断了；Argus 用 AgentTeams + 可核验证据重建发布门禁。”**
> 页序按“必交二”八项要求组织：场景→架构→三层约束→Agent→Skill→工具与可观测→评估→Demo→复赛路线图→安全→开源。

## 1. 封面

- 项目名：Argus：AI 代码发布安全门禁
- 一句话：把 AI 生成代码的每次变更，转化为可运行、可验证、可审计的发布决策
- 赛道：Agent Infra
- 当前进展：8 评估 Agent 设计（dep/arch/code/sec/perf/robust/delivery/atk），已跑通六 Worker 闭环 + 自动化评测数据

## 2. 场景、用户与痛点

- 场景：AI 生成或大幅修改代码后，准备合并、发布或部署时，缺乏可信检查
- 用户：AI 应用开发团队、平台工程团队、安全与交付负责人
- 痛点：
  - 依赖幻觉与不存在包
  - 占位实现看似完整
  - 安全漏洞和硬编码密钥
  - CI 有测试但没有执行
  - LLM review 自身可能产生幻觉证据
- 现状缺口：扫描器给告警、Agent 给结论，但缺少统一证据链与发布门禁

## 3. 价值与行业可复制性

- 短期切入：变更驱动的 AI 应用发布安全门禁
- 长期方向：广义 AI Agent 安全平台
- 用户获得：
  - 发布前明确的 pass/warn/block/unknown
  - 每条 finding 可回到固定快照、路径、行号与规则版本
  - Agent 失败或证据不足不伪装成功
  - 报告可用于工程修复、复核和审计
  - 越用越强：数据飞轮驱动 Skill/Worker 灰度自迭代，审计越多规则越准、成本越省（见 §13E）
- 行业可复制性：
  - 同样面向“AI 生成内容进入关键业务链路”的信任问题
  - 可复制到金融、政务等强合规行业的代码交付与发布审批
  - 门禁方法论可平移：采购验收、合同合规、运维变更等企业任务闭环

## 4. 系统架构

```text
单项目门禁管线：

AuditRequest → Preflight → Immutable Snapshot → Scheduler
                                            │
     8 assessors: dep / arch / code / sec / perf / robust / delivery / atk
                                            │
                                    Meta Evidence Gate
                                            │
                             Synth + Deterministic Policy
                                            │
                        report.json / report.md / exit code

规模化（大项目/多仓库）：argus-splitter → 子项目(各自 snapshot+DAG)
   → 各自 assessor→meta→synth → final-synth → 统一报告

AgentTeams: Project Room + Matrix + MinIO DAG + 8 assessors + Meta/Synth gates
            + splitter/final-synth（规模化）+ locked Skills
```

- Audit Data Plane 是发布门禁唯一真相源
- Observability 只读，不反向修改 finding 或 policy
- 同一不可变快照供给所有 Worker，杜绝“各看各的版本”
- 规模化时由 `argus-splitter` 先拆子项目、`final-synth` 合并统一报告（见 §6 / §13A）；单项目门禁管线不变

## 5. 三层架构：确定性形式层 × 语义判断层 × 贯穿全程的机器强约束

设计目标：不用“约定 + 事后校验”，改用“事前强制”——LLM 负责语义，确定性代码负责放行。

| 层 | 职责 | Argus 落地 |
|---|---|---|
| 确定性形式层（扎实） | 可机器校验的形式约束：快照、哈希、schema、CAS、引用完整性 | 不可变快照 + source hash、digest 引用、严格 schema、幂等键 + revision CAS、Skill 目录 digest 锁 |
| 语义判断层 | LLM 语义研判，不可确定性化（依赖真伪、注入是否成立、测试是否真执行） | 8 个评估 Agent 产出 finding；Meta 独立复核证据、标记 HALLUCINATION |
| 机器强约束层（贯穿全程） | 凡能用确定性代码强制的地方，不用 prompt 约定；事前强制而非事后校验 | fail-closed 策略、required Agent 缺失不得 pass、证据门禁、脱敏 + HMAC（DAG 校验、状态 ACL 等补强见 §13D） |

贯穿原则（对应路线图 P1–P6）：

- **机器强约束优先于约定**：DAG 校验、字段 ACL、版本 CAS、schema 校验全部走确定性代码
- **生成与校验分离**：LLM 可自由决策，但出不了机器闸门
- **fail-closed 单向保守**：任何降级只让结论更保守（pass→warn→unknown→人工介入），绝不静默 pass
- **元数据与原始内容分离**：trace / Matrix / 报告只记标量元数据，不记源码、密钥、raw prompt、私有推理
- **独立验证不可自评**：Meta 只核验，不创造 finding，也不决定 release gate

落地状态：形式层与门禁强约束骨架已上线（fail-closed、Skill 锁、schema、CAS）；机器强约束层的 DAG 校验、状态 ACL、失败重试、语义级复核等补强并入复赛路线图（§13）。

## 6. Agent 分工与任务拆解

评估侧设计为八个 Agent + 两级确定性门禁（Meta 证据核验、Synth 策略/报告）；规模化（大项目/多仓库）再增 `argus-splitter`、`final-synth` 两个编排 Agent（复赛，§13A）。身份与 Skill 绑定，模型不可自行增减安全检查。

| Agent | 任务拆解 | 输入 → 输出 | 状态 |
|---|---|---|---|
| `argus-dep` | 解析 manifest → 对照 registry → 找不存在/版本异常依赖 | SourceSnapshot → AgentResult\<dep\> | 已实现 |
| `argus-arch` | 架构依赖与分层合规审计 | SourceSnapshot → AgentResult\<arch\> | 规划中 |
| `argus-code` | 扫描占位实现 → 检查代码契约/状态机 | SourceSnapshot → AgentResult\<code\> | 已实现 |
| `argus-sec` | 静态安全规则 → 密钥泄漏 → 注入类漏洞 | SourceSnapshot → AgentResult\<sec\> | 已实现 |
| `argus-perf` | 性能风险与资源边界审计 | SourceSnapshot → AgentResult\<perf\> | 规划中 |
| `argus-robust` | 鲁棒性与异常路径审计 | SourceSnapshot → AgentResult\<robust\> | 规划中 |
| `argus-delivery` | CI workflow 与测试文件交叉比对 → 验证测试确实执行 | SourceSnapshot → AgentResult\<delivery\> | 已实现 |
| `argus-atk` | 攻击面与对抗性探测审计 | SourceSnapshot → AgentResult\<atk\> | 规划中 |
| `argus-meta` | 逐条核验 finding 的 path/line/hash/evidence，标记 HALLUCINATION | findings → MetaDecision | 已实现 |
| `argus-synth` | 按确定性策略聚合 VERIFIED finding → 门禁结论 + 报告物化 | MetaDecision → PolicyDecision | 已实现 |
| `argus-splitter` | 按模块边界拆分独立子项目（各自 snapshot + DAG） | SourceSnapshot → SubProjectPlan | 规划中 |
| `final-synth` | 合并各子项目报告为统一报告，处理跨模块 finding | SubProjectReports → UnifiedReport | 规划中 |

- 当前已跑通 dep/code/sec/delivery + Meta + Synth 的六 Worker 闭环；arch/perf/robust/atk 按同一契约扩展，不改变门禁语义
- `argus-splitter` / `final-synth` 为规模化编排 Agent（复赛，见 §13A），仅大项目/多仓库启用，不改变单项目门禁语义
- 每个 audit 映射为一个 Project Room，职责内聚、故障隔离
- assessor 可并行；Meta 依赖全部 assessor；Synth 依赖 Meta

## 7. 协作流、上下文与异常分支

协作流（上下文传递）：

```text
snapshot_id
  → detector/rule version
  → finding(path, line, source_sha256, evidence)
  → MetaDecision(label, reason_codes)
  → PolicyDecision(release_gate, reasons)
  → immutable report
```

- 上下文边界：Worker 只见本任务类型化工件与固定快照；Matrix 只传 task ID、spec 路径与状态；自然语言 `result.md` 不能替代机器工件
- 异常分支：
  - `REVISION_NEEDED` → 创建 revision → Meta recheck
  - `BLOCKED` → 进入 human-wait，等待人工处置
  - required Agent 缺失/失败 → `unknown`，不得 `pass`
  - Skill digest 不匹配 → 分发失败，任务终止
  - Worker/Project/Matrix/MinIO 任何错误必须显式失败，不得静默吞掉

## 8. 核心 Skill：审计能力的最小可执行单元

Skill 不是"Agent 随手调用的工具"，而是 Argus 把审计方法论固化为**自包含、可执行、可版本化、可验证**的代码单元——它是「机器强约束层」（§5）的实际落点。没有 Skill，Argus 就退化为"LLM 给意见"；有了 Skill，Argus 才成为"机器可审计的门禁"。

Skill 承担的三层角色：

1. **承载审计能力（取代 LLM 自由发挥）**：每个评估域封装为 Skill——检测规则（依赖比对、密钥扫描、CI 策略、占位实现）+ 证据格式 + 禁止条件，以确定性 Python 实现为主（`implementation/main.py --input --output`），不 import 宿主 `core.*`；按 §5 分层，Skill 负责可机器校验的硬约束，语义研判归语义判断层由 LLM 承接
2. **门禁的确定性来源**：`argus-release-policy-evaluate` 是规则引擎，明令"**不得调用 LLM 自由决定 gate**"——发布结论只认证据，不认模型意见
3. **反幻觉与强约束的执行点**：`argus-evidence-verify` 用机器标签把关（`VERIFIED / NEEDS_EVIDENCE / INCONSISTENT / HALLUCINATION / NOT_ACTIONABLE`）；`argus-finding-emit` 强制每条 finding 携带 path/line/hash/evidence

| Skill | 承担角色 | 输出 |
|---|---|---|
| `argus-finding-emit` | 评估域统一证据出口 | schema 化 finding |
| `argus-evidence-verify` | 反幻觉门禁（Meta） | MetaDecision |
| `argus-release-policy-evaluate` | 确定性发布门禁（Synth） | PolicyDecision（pass/warn/block/unknown） |
| `argus-report-materialize` | 原子报告物化（Synth） | report.json / report.md |

版本化与可复现——为什么 Skill 对项目不可替代：

- 完整目录 digest 锁 + 语义版本，禁止运行时拉取 `latest` → 同版本 Skill 保证门禁决策可复现（确定性纯函数，§11）
- 输入/输出/错误 schema + 明确禁止条件 → finding 可被机器复核，杜绝 LLM 口头结论
- Controller-owned ZIP 分发 + Worker registry 双重验收 → 无未审代码进入门禁
- **Skill 版本 = 数据飞轮的最小原子**：自迭代产出新版本，shadow/canary 灰度通过才晋级（§13E）——Skill 越用越强，是项目长期价值的载体

## 9. 工具链、云产品与企业系统规划

现状工具链：

- 编排：AgentTeams v1.2.0-beta.1（Project Room、Matrix、MinIO task DAG）
- 运行时：openclaw + Docker 容器镜像 `agentteams/worker-agent:...-argus.7`
- 模型：deepseek-v4-flash（各 Agent 统一，成本可控）
- 配置中心：Nacos（Skill 锁定与分发）
- 存储：MinIO 类型化任务工件；本地 SQLite（state.db）记录状态机

云产品 / 企业系统接入等复赛规划并入 §13 复赛路线图。

## 10. MCP、RAG 与可观测规划

- MCP：仅开放元数据类只读 MCP——registry 查询、CI 状态、SBOM 校验；禁止源码、密钥、原始 prompt 出网
- RAG：版本化 registry/SBOM/规则库作为受控证据知识，运行时仅本地检索；Skill 锁定即“知识版本冻结”，杜绝知识漂移
- 可观测：初赛 builtin trace recorder（allowlist 结构化事件、有界标量 attributes、JSONL 本地落盘）；复赛升级 OTel/LoongSuite + AgentScope Studio（见 §13）

## 11. 评估指标

评测不变量（自动化，`demo/eval` 已实现 harness/gate）：

- vulnerable 100% block，fixed 100% pass
- Meta 必须拦截幻觉 finding（虚构 path/line 不进入主报告）
- required Agent 不完整不得 pass
- finding 的 path/line/hash/evidence 可复核
- 门禁决策确定性：同一证据集 → 同一 `release_gate`（确定性纯函数）；多次 run 的 finding 用语义去重评估，不做逐字节一致断言
- 全量自动化测试与安全泄漏自检通过

## 12. Demo 落地计划

Demo 场景（`demo/scenarios/ai-pr-three-defects`，vulnerable 与 fixed 两个版本）：

1. 不存在的依赖 → Dependency finding
2. SQL 字符串拼接注入 → Security finding
3. CI 只编译、未运行已有测试 → Delivery finding
4. 注入虚构文件行号 → Meta 标记 HALLUCINATION 并排除

演示脚本：

- 运行 `argus audit`（headless）→ 展示 block 门禁、退出码 2、报告各 finding 证据
- 切换 fixed 版本 → 展示 pass 门禁、退出码 0
- 强调两次 snapshot ID 不同、旧报告不覆盖
- 现场可选：live AgentTeams 实时编排展示（依赖 Docker/AgentTeams 环境；当前展示已落地 Worker 子集）

落地计划：

- 已完成：headless CLI、六 Worker 编排（8 Agent 设计的已落地子集：dep/code/sec/delivery + Meta/Synth）、Skill 锁、Meta 门禁、原子报告、trace recorder
- 下一步（复赛阶段）见 §13：补齐 arch/perf/robust/atk 四类评估 Agent、真实 Git 接入、增量调度、canary/shadow 评估

## 13. 复赛路线图：规模化上下文 × AI 应用安全面 × 数据飞轮

复赛阶段统一规划，汇总全篇分散的复赛事项（工具链扩展、可观测升级、强约束补强、评估灰度、Skill/Worker 自迭代与数据飞轮均在此集中）。

### A. 规模化上下文架构（多 Worker 上下文）

- **上下文隔离**：Worker 独立会话与工作区，杜绝跨项目污染——`memory/`、`SOUL.md`、sessions 按 `project_id` 命名空间隔离，切换项目时清理
- **大项目分片（>1M tokens）**：snapshot 阶段生成 chunk-index（按模块/包分组，≤50K tokens）+ LLM 语义摘要；assessor 只读相关 chunk，不做全量上下文
- **子项目分解**：Layer 0 `argus-splitter` 按模块边界拆分 monorepo 为独立子项目（各自 snapshot + DAG），`final-synth` 合并跨模块报告
- **增量审计与断点续跑**：生成不可变 project snapshot（约 5K tokens）+ diff 引擎，只重扫变更文件，`resume_token_estimate` 让恢复成本可见

### B. AI 应用安全审计面（LLM 输入/输出边界）

初赛 4 类 assessor 审查的是静态产物（源码→构建→依赖→发布）；复赛扩展审查**动态交互链**（RAG 检索 → 提示拼接 → 推理 → 工具调用 → 响应生成）：

- **RAG 数据泄露**：提示注入提取、RAG 越权、引用溯源泄露、Canary 回显
- **AI 安全测试**（OWASP LLM01/02/06）：直接/间接提示注入、多轮越狱、RAG 权限边界
- **Agent 运行时诊断**：幻觉行为、tool-call 循环、LLM-Judge 失效检测、成本异常
- **Token 成本审计**：调用热点、提示膨胀、上下文浪费、缓存缺失、工具冗余、模型选择不当
- **审计基元**：Adversarial probe（对抗探测）、Trace replay（行为回放）、Boundary fuzzing（边界模糊）

### C. 存储利用与学习闭环（Query / Snapshot / Knowledge 三层）

- **Query Layer**：结构化索引 + 跨项目检索（“过去 6 个月与 auth 相关的全部 finding”）
- **Snapshot Layer**：不可变项目快照 + 增量恢复（“恢复到项目 X 完成时的精确状态”，免重审未变更文件）
- **Knowledge Layer**：finding 向量库、模式聚类、规则提取（“这段代码像项目 Y 的 bug”）

### D. 工程化落地与接入

- 补齐 arch/perf/robust/atk 四类评估 Agent，统一契约接入门禁
- 云产品：容器服务/K8s 承载 Worker，S3 兼容对象存储、消息队列、KMS 托管敏感配置
- 企业系统：Git（MR 触发器）、CI/CD（门禁插件）、工单、资产与漏洞管理系统回写；任何外部接入保持 Audit Data Plane 为唯一真相源，观测系统只读
- 可观测升级：OTel/LoongSuite + AgentScope Studio，链路追踪覆盖全部 Agent 与门禁决策
- 机器强约束补强：DAG 结构校验、状态字段 ACL、失败重试与人工介入、语义级复核
- 评估与灰度：增量调度、canary/shadow 评估、AgentVersion 晋级

### E. Skill / Worker 自迭代与数据飞轮

数据飞轮闭环：

```text
audit → findings/评测 → Knowledge Layer 落库（§13C）→ 规则/规则集提取
   → 新 Skill 候选版本（shadow）→ canary/灰度评估 → AgentVersion 晋级
   → 下次 audit 更强，循环复用
```

- **Skill 自迭代**：误报/漏报与失败样本回流 Knowledge Layer，自动生成规则候选；人工复核后晋级为锁定版本
- **Worker 自迭代**：AgentVersion 晋级以历史 precision/recall、token 成本、稳定率为判据，表现差版本可回滚
- **发布走灰度**：锁定版本保证可复现；候选版本并行 shadow/canary，灰度通过率达标才晋级，失败即拦截或回滚——「知识版本冻结」防漂移与自迭代并存

## 14. 安全边界与风险控制

- 不执行目标源码、不安装目标依赖、不触发 CI/部署
- 目标仓库文字全部视为不可信数据，防 prompt injection
- 外部查询只允许元数据；源码不出网
- 密钥只保留脱敏值或 HMAC fingerprint
- trace 禁止源码、原始 prompt/response、private reasoning
- 门禁放行必须证据完备：required Agent 缺失 → unknown；Skill digest 不匹配 → 分发失败
- 风险控制主张：宁可误拦（block），不可放行未经核验的变更

## 15. 开放或开源计划

- Apache-2.0 开源
- 开放 Agent Identity、Skill schema、锁定与分发方法
- 开放三缺陷样例、评测不变量与 `demo/eval` harness
- 可扩展到架构、性能、鲁棒性 assessor
- 可接入企业 Git、CI/CD、工单、资产与安全系统
- AgentTeams 编排方法可复用于合规、采购、运维等企业任务闭环
