# 多 Agent 安全编排 — 诊断与实施路线图

> 生成日期：2026-08-15
> 来源：本项目多轮代码评审的诊断结论（6 条现状评估）+ 目标方案（7 条架构设计）+ 既有上下文架构设计，去重整合而成。
> 说明：散落于多处的重复原则已提炼为第 1 节「核心原则」；各方案不再重复表述这些原则，仅保留其特有内容。

---

## 0. 一句话诊断（根因）

**确定性形式层扎实，语义判断层和贯穿全程的"机器强约束"层系统缺位——用"约定 + 事后校验"替代了"事前强制"。**

具体表现各不相同（幻觉只防引用、DAG 丢硬约束、失败无重试、状态无 ACL），但病根一致。本文档的路线图，就是把这根因逐层替换成机器强约束。

---

## 1. 核心原则（去重提炼，全文判据）

| # | 原则 | 含义 |
|---|---|---|
| P1 | **机器强约束优先于约定** | 凡能用确定性代码强制的地方（DAG 校验、字段 ACL、版本 CAS、schema 校验），不用 prompt / 自然语言约定 |
| P2 | **生成与校验分离** | LLM 负责灵活生成（DAG / finding / 报告），确定性校验器负责验证；LLM 可自由决策，但出不了机器闸门 |
| P3 | **fail-closed 单向保守** | 任何降级 / 删除 / 熔断 / 对账删减，只能让结论更保守（pass→warn→unknown→人工介入），绝不静默 pass |
| P4 | **元数据与原始内容分离** | 观测 / 共享 / 追溯层只记标量元数据（token / 耗时 / 重试 / error / 来源 id），不记敏感原文（源码 / 密钥 / raw prompt / 私有推理） |
| P5 | **独立验证不可自评** | ground truth、下游复核的判据必须独立于被验证者（Meta 不能既当考生又当考官） |
| P6 | **语义层不可确定性化** | 确定性校验只能覆盖形式 / 引用 / 结构；语义正确性需 LLM 研判，是单独一层，不能打包进确定性校验器 |

---

## 2. 现状诊断（浓缩缺口清单）

**已有的正确基础**（不要重做）：不可变快照（`core/snapshot.py`）+ hash 校验、digest 引用（`agentteams/worker_payloads.py`）、幂等键 + revision CAS（`agentteams/protocol.py`）、严格 schema 解析、fail-closed（`core/policy.py`）、局部失败隔离（`cli/argus.py` `_run_assessors`）、脱敏 + HMAC 指纹（`core/redaction.py`）。

**系统性缺口**（按维度）：

1. **幻觉防控**：MetaReviewer（`core/meta.py`）只核验引用（path/line/hash），不核验语义；`context_lines` 内容不比对（只查非空）；HALLUCINATION 从报告剔除但对语义幻觉失效。
2. **引擎一致性**：`--engine local` 直跑确定性 Meta，`--engine agentteams`（默认）走 Manager LLM 对话协调（`agentteams/orchestrator.py`），Argus 端只做 gate 枚举校验——README 宣传的"确定性 gate"在真实 E2E 不强制。
3. **编排依赖**：无 DAG 校验器（环/孤立/重复）；DAG 依赖图（`worker_payloads.py` 的 digest 引用）没接到默认执行链路。
4. **状态管理**：共享状态是 MinIO 文件约定（`_shared_relative` 只校验路径前缀），无字段级 ACL、无 writer_id / 版本号 / 变更审计；消息总线 Matrix fire-and-forget（`hiclaw_client.py`）无 ack / 重投。
5. **失败恢复**：无执行失败重试（重试只在 ACK 层）、无降级、无运行时人工介入（`protocol.py` `TaskState` 无 HUMAN_WAIT 态）、无 checkpoint 复用（token 浪费）。
6. **观测与评测**：`core/tracing.py` 是最小雏形，无 token / 耗时 / 成本 / 告警；无回归评测集、无灰度（只有一次性 `acceptance/` + 2 个 demo 场景）。

---

## 3. 目标架构（六层蓝图）

```
① 编排层    planner 生成 DAG ──► 校验器(结构+业务) ──► 角色边界
② 执行层    每个 agent 输出边界 ──► 校验器(格式+事实+一致性) ──► 反馈闭环
③ 状态层    共享状态版本化(version/writer/events) + 存储层 ACL
④ 可靠性层  超时 ─► 重试 ─► 熔断 ─► 关键性分流(人工介入/显式降级)
⑤ 观测层    全记录元数据 + 成本聚合 + 跨 run 查询
⑥ 评测层    回归评测集 + 版本 pin 门禁
```

六层之间的数据流：①产出 DAG → ②按 DAG 执行并校验产出 → ③记录谁写了什么 → ④兜住失败 → ⑤采集元数据供 ⑥ 评测，⑥ 反过来验证 ①-④ 的变更是否真的变好。

---

## 4. 实施路线图（分阶段、带依赖）

> 标注约定：`[零风险]` 纯确定性代码，可独立先做；`[需产品决策]` 需要拍板；`[依赖 R-x]` 前置依赖。

### 阶段 0 — 地基（零风险，多方案共享前置，可立即做）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R0.1 | 确定性校验函数拆分 | 代码 | — | 把 `core/meta.py` 的 `_decide` 拆成可复用 `verify_finding(snapshot, finding)`，供每个 agent 输出边界调用 |
| R0.2 | 共享状态版本化 | 代码 | — | 每个共享对象加 `version` / `written_by` / `updated_at`，变更 append 到 `events.jsonl`（满足可追溯 + 防乱改 CAS 地基） |
| R0.3 | AgentResult 元数据补全 | 代码 | — | 填 `started_at/finished_at`、耗时、重试次数、error；token 从 AI Gateway 挂钩子（不是本地加字段） |
| R0.4 | 评测集建设 | 内容 | — | demo 的 2 场景扩到「简单 / 复杂 / 异常」三类；ground truth 独立标注，**不走 Meta 判据** |

### 阶段 1 — 校验层（依赖 R0.1）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R1.1 | DAG 结构 + 业务校验器 | 代码 | R0.1 | 环(DFS) / 孤立(可达性) / 重复(归一化去重)；业务约束 = `scheduler.py` `MANDATORY_AGENTS` 升级为对 LLM 生成 DAG 的校验规则；校验失败 fallback 到静态默认 DAG（宁多审不少审） |
| R1.2 | 结果校验下沉 + 反馈闭环 | 代码 | R0.1 | 格式 + 事实校验放到每个 agent 输出边界；打回重生成（重试 2 次）；反馈措辞"重新判断真实性"而非"改到过校验"（防 reward hacking） |

### 阶段 2 — 状态 / 边界层（依赖 R0.2）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R2.1 | 存储层写权限 ACL | 代码 | R0.2 | `_shared_relative` 加 writer 只能写自己名下 key 的检查（`argus-dep` 只能写 `*dep*.json`），把文件名约定升级为强制 ACL |
| R2.2 | 角色边界四层拦截补全 | 代码 | R2.1 | 工具白名单(已有 `WORKERS.skills`) + 数据写 ACL + 数据读范围 + 职责语义校验；补缺的"数据写/读"两层 |

### 阶段 3 — 可靠性层（依赖 R0.3、R1.1）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R3.1 | 重试 + 熔断 + 超时 | 代码 | R0.3 | `_run_assessors` except 分支加 retry loop，重试 N 次标熔断；熔断粒度 = 节点级（非类型级） |
| R3.2 | HUMAN_WAIT 态 + resume | 代码 | — | `TaskState` 加 HUMAN_WAIT；CLI 加 `argus resume --run-id --decision=retry|skip|unknown|abort`；状态持久化 |
| R3.3 | 关键性分级 + 显式降级 | 代码 | R1.1 | planner 标关键性 + 校验器确认；非关键失败 → 标 `NOT_AUDITED` + coverage 显式写"XX 域未审计"，**不静默跳过** |

### 阶段 4 — 对账 / 观测层（依赖 R0.2、R0.3）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R4.1 | 报告溯源对账 | 代码 | R0.2 | 结构化断言（gate / findings / 计数）反查共享状态；区分"无依据(编造)"与"被篡改(不一致)"；**对账后 gate 从共享状态重算，不信任 LLM 写的 gate**；自由文本 summary 隔离标注、不参与 gate |
| R4.2 | 成本聚合 + 跨 run 查询层 | 代码 | R0.3 | 观测数据持久化，按 agent 出「token 占比 / 耗时占比 / error 率 / 重试率」三张表；瓶颈按耗时/token/稳定性三维度分别出 |

### 阶段 5 — 评测门禁（依赖 R0.4、R0.3）

| ID | 事项 | 类型 | 依赖 | 说明 |
|---|---|---|---|---|
| R5.1 | 评测 harness | 代码 | R0.3, R0.4 | 每场景跑 N 次取统计；质量(vs ground truth)与一致性(方差)分开测；先定质量/成本权重（如"成本+30% 除非质量+15% 否则不接受"） |
| R5.2 | 版本 pin + 评测门禁 | 流程 | R5.1 | 变更→跑评测→指标对比→达阈值才升版本；复用已有 `contract.lock.json` / `skills.lock.json` pin 机制 |

---

## 5. 规模与产品维度（context-architecture 独立项）

以下内容来自既有「多 Worker 上下文架构」设计，**与上述安全编排路线正交**，需单独排期，本路线图不覆盖：

- **大项目分片**（>1M tokens）：chunk-index 语义摘要、sub-project splitter（Layer 0 拆分 worker）——规模问题，非安全编排问题。
- **跨项目污染隔离**：worker `memory/` / `SOUL.md` / sessions 按 project_id 命名空间隔离 + 切换清理。
- **冷启动恢复**：项目 closure snapshot + diff-based incremental audit（"只重扫变更文件"）——**与 R0.2 的 checkpoint 复用是同一件事，已在阶段 0 合并**。
- **AI 应用审计盲区**：传统静态审计（源码→构建→依赖→发布）未覆盖 AI 应用的动态交互面（RAG 泄露 / 提示注入 / 循环调用 / token 成本）——**这是产品定位层面的 gap，不是工程路线能解决，需另行立项**。

---

## 6. 决策待办（需要产品拍板）

| # | 决策 | 影响 |
|---|---|---|
| D1 | 报告是否允许 LLM 自由叙述（executive summary）？ | 允许 → 必须接受"summary 不可对账、只能标注、不参与 gate"；禁止 → 报告纯结构化 |
| D2 | 评测集 ground truth 由谁标注？ | 决定 P5 独立性能否成立；人标注 vs 独立 reviewer |
| D3 | 质量 / 成本 / 耗时的权衡权重？ | 决定 R5.1 评测能否出可执行结论 |
| D4 | 灰度形态：版本 pin 门禁 vs 切真实流量？ | 本产品是"手动触发审计"非高流量服务，推荐版本 pin + 评测门禁 |
| D5 | 非关键 agent 降级的底线？ | 哪些域绝不可静默跳过（建议 sec/dep/delivery 恒为关键） |

---

## 附：依赖总览

```
阶段0 地基(独立并行): R0.1 R0.2 R0.3 R0.4
        ↓
阶段1 校验: R1.1←R0.1   R1.2←R0.1
        ↓
阶段2 边界: R2.1←R0.2 → R2.2
        ↓
阶段3 可靠: R3.1←R0.3   R3.2(独立)   R3.3←R1.1
        ↓
阶段4 对账观测: R4.1←R0.2   R4.2←R0.3
        ↓
阶段5 评测: R5.1←R0.3,R0.4 → R5.2

最小可落地第一步：R0.1 + R0.2 + R0.3（三个纯确定性地基，零风险、不依赖任何前序、多方案共享）
```
