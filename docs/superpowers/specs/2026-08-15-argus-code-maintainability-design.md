# Argus Code 可维护性审查 Design

> **Date**: 2026-08-15
> **Status**: Approved (design review) — awaiting implementation plan
> **Scope**: 仅 `code` agent 的可维护性扩展；arch / perf / robust / atk 不在本 spec 内（atk 明确跳过）

---

## 1. 背景与目标

设计 spec `2026-08-01-argus-v2-design.md`（v2 内已删，现存活于非 v2 目录 `E:\heishou\Argus\docs\superpowers\specs\2026-08-01-argus-v2-design.md`）给 `code` agent 规划了职责：

> **Code Auditor**: Naming quality, function responsibility (long funcs, too many params), error message quality, AI placeholders, state machine completeness, idempotency, concurrency safety

当前实现只覆盖了 `AI placeholders`（`agents/code/detector.py` 的 `code.placeholder` 一项）。**可维护性审查是设计时就规划、一直欠着的范围。**

恢复的项目文档 `AI代码可维护性与数据建模.md`（2026-08-15 从会话记录找回）第 14 节给出了确定性可检测的「屎山信号」清单（数据结构 / 业务建模 / 代码结构三类），是本次规则集的直接来源。该文档同时提供 §13.2 可直接复用的 AI 编码约束，用作 finding 的 remediation 文案。

**目标**：给 `code` agent 补上可维护性审查维度——确定性规则（低误报优先），覆盖文档 §14.1（数据结构）主线 + §14.2/14.3 可规则化的子集。产出 advisory（medium/low）finding，只 warn 不 block。

## 2. 范围

### 2.1 在本 spec 内

- 新增可维护性规则集（11 条，见 §4），确定性、纯静态分析、可单测。
- 两套引擎同步落地：本地引擎（`agents/code/`）+ AgentTeams skill（`argus-code-maintainability-scan`）。
- `argus-code` worker 同时挂 `argus-code-rule-scan` + `argus-code-maintainability-scan`（一个 agent 多 skill 的既定模式）。
- 评测：新增 `simple-maintainability` 场景 + ground-truth，并验证 `simple-clean`（零误报）不回归。

### 2.2 不在本 spec 内（后续单独迭代）

- **arch / perf / robust**：3 个缺失 assessor，同套确定性模式，各自单独设计。`core/scheduler.py` 已有它们的路由条目，本 spec 不动调度器。
- **atk**：明确跳过。需要真实 LLM API + Meta/LLM 研判基础设施（当前未实现），独立前置工程。
- 语义型检查（god-function 职责判断、命名质量全量、注释/意图、无约束字典、跨文件重复条件）——见 §8 推迟清单。
- 修改发布门禁语义（可维护性永不 block）——§6。

## 3. 架构

### 3.1 规则引擎形态

核心约束：**skill 必须 standalone（无 host import）**——`argus-code-rule-scan` 的 `implementation/main.py` 明确 "No host imports"。因此规则集不能只放 host 侧。

**方案：规则实现为纯函数模块，两侧共用，配 parity 测试防漂移。**

- **规则模块**：`skills/argus-code-maintainability-scan/implementation/rules.py` —— 纯 stdlib，无 host import。接口：
  ```python
  @dataclass(frozen=True)
  class RuleHit:
      rule_id: str
      category: str
      severity: str   # "low" | "medium"
      confidence: float
      line_start: int
      line_end: int
      title: str
      detail: str
      remediation: str
      excerpt: str     # 脱敏后的命中行摘录

  def scan_path(path: str, text: str) -> list[RuleHit]: ...
  ```
- **skill adapter**：`implementation/main.py` 读 payload（`source_root` + `files`），对每个快照文件调 `scan_path`，转成 schema-valid finding（补 `id`/`fingerprint`/`evidence`）。镜像 `argus-code-rule-scan` 的输入输出协议（`--input`/`--output` JSON，`schema_version: 1`，失败 exit 2）。
- **本地 detector**：`agents/code/detector.py` 新增对 `rules.scan_path` 的调用（通过 sys.path 加 skill 目录引入；该模块是纯 stdlib，host 侧引入它不违反 standalone 约束——约束方向是 skill 不能依赖 host，反向允许）。保留现有 `code.placeholder` 逻辑不动。
- **parity 测试**：同一份语料分别跑 skill adapter 与本地 detector，断言产出 finding 的 `(category, file, line_start)` 集合一致。防两侧规则漂移。

> **fallback**：若 host 引入 skill 规则模块的 import path 在打包/测试环境不可靠，退化为「规则集复制两份 + parity 测试」——同样的防漂移保证，代价是重复代码。实现时优先单模块方案。

### 3.2 数据流

```
SourceSnapshot (files + sha256)
        │
        ▼
code agent（本地: agents/code/detector.py；agentteams: argus-code worker 调 skill）
        │  对每个 .py/.js/.ts/.java 文件跑 scan_path
        ▼
RuleHit → Finding(agent="code", category="code.*", severity=low|medium,
                  evidence={context_lines=(redacted_excerpt,), source_sha256, detector="code.<rule>"})
        │
        ▼
meta 核验（现有 verify_agent_result 幻觉拦截，不做 LLM 差异）→ synth 汇总 → policy
        │
        ▼
policy.evaluate_policy：severity low|medium → warning（不 block）
```

### 3.3 语言范围（v1）

**v1 全部 11 条规则仅扫描 Python（`.py`）**，用 AST-lite + 缩进/结构跟踪。跨语言（`.js/.ts/.java/.go/.rs`）统一留 v2——eval fixture 是 Python，且跨语言解析会放大 FP，v1 以 FP 控制优先。文本类规则（魔法数字/裸字符串/映射链/or-chain）原则上是语言无关的，但 v1 仍限 Python，避免 JS/TS 等语法差异引入误报。

## 4. 规则集（11 条）

> 出处标注：[doc]=《AI代码可维护性与数据建模.md》；[spec]=2026-08-01 设计 spec。所有 finding `agent="code"`。remediation 直接引用 doc §13.2 约束。

| rule_id | category | 信号 | 检测语义 | 严重度/置信 | 出处 | FP guard |
|---|---|---|---|---|---|---|
| CODE-101 | `code.function_length` | 长函数 | `def <name>(` 起，函数体（去空行/注释）> 100 行 → 命中 def 行 | low / 0.85 | [spec] | 只数非空非注释行；忽略装饰器；嵌套函数按缩进归属 |
| CODE-102 | `code.too_many_params` | 过多参数 | `def` 参数 > 6（排除 `self`/`cls`/`*args`/`**kwargs`） | low / 0.9 | [spec] + doc §14.2 | 仅 Python |
| CODE-103 | `code.deep_nesting` | 深层嵌套 | 控制流嵌套深度（if/elif/for/while/with/try/def）≥ 4 | medium / 0.8 | doc §14.3 | 深度超过 4 即停，不累计重复计数 |
| CODE-104 | `code.magic_number` | 魔法数字 | 数值字面量作为**算术操作数**（另一侧是裸标识符），如 `price * 0.8`；白名单 {0,1,-1,2} | low / 0.75 | doc §1.1 | 比较操作数不算（`status == 200` 不报）；只报算术上下文 |
| CODE-105 | `code.bare_string_enum` | 裸字符串状态 | 同文件 ≥3 个不同的小写蛇形字符串用于比较/成员判断（`== "pending"`、`in {"paid",...}`）→ 疑似状态枚举 | medium / 0.8 | doc §8.4/§14.1 | 只认全小写无空格类枚举值；显示文本（含大写/空格）不算；报首次出现 |
| CODE-106 | `code.boolean_state_flags` | 多布尔互斥 | 同一函数作用域内 ≥3 个 `is_*`/`has_*` 布尔被赋值 → 疑似互斥状态 | medium / 0.7 | doc §8.3/§14.1 | 仅 Python；只在赋值语句统计，不含类属性 |
| CODE-107 | `code.mapping_if_chain` | if/elif 映射链 | ≥4 个分支，每分支体是**单个 `return <literal>`** → 纯映射 | medium / 0.85 | doc §8.5/§14.1 | 分支体必须恰好一个 return 字面量；else 可选 |
| CODE-108 | `code.or_chain_membership` | OR 链成员判断 | ≥3 个 `x == "a" or x == "b" or x == "c"` 比较同一 LHS → 应改 `x in {...}` | medium / 0.85 | doc §5.2/§14.1 | 同变量 ≥3 个 or 分支；仅字符串字面量 |
| CODE-109 | `code.parallel_arrays` | 平行数组 | 模块顶层 ≥3 个列表字面量 + 同一循环里用同一索引变量访问其中 ≥2 个 → 应改业务对象/索引 | low / 0.6 | doc §5.3/§14.1 | 需 `list[i]` 同索引访问证据；启发式，置信低 |
| CODE-110 | `code.linear_scan_no_index` | 线性查找缺索引 | 嵌套循环 join：`for a in A: for b in B: if a.k == b.k` → 应先建 `B` 索引 | medium / 0.7 | doc §5.4/§8.6/§14.1 | 内层遍历不同集合 + 字段相等比较；仅 Python |
| CODE-111 | `code.single_letter_param` | 单字母参数名 | 函数参数为单字母（`def f(x, y, z)`） | low / 0.9 | doc §1.1 + [spec] naming quality | 排除 `self`/`cls`；仅 Python 结构规则 |

**严重度语义**：`code.*` 维护性 finding 全为 low/medium → policy 只 warn 不 block（§6）。MEDIUM 规则的置信 ≥0.7，LOW 规则 ≥0.6，均低于 `cfg.policy.min_confidence` 门槛的考量见 §6。

## 5. P4 合规

- finding 的 `evidence.context_lines` 只存**脱敏后的命中行摘录**（复用 `core/redaction.py` 的 `redact()` / `hmac_fingerprint()`；skill 侧用 `_shared` 同款 `_redact`/`_fingerprint`）。源码正文永不进入 finding。
- `id`/`fingerprint` 用 hmac（salt 固定），不泄露路径外信息。
- skill 的 SKILL.md 保留「禁止」条款：禁执行目标代码、禁泄露源码/secret/原始推理（与 `argus-code-rule-scan` 一致）。
- 规则引擎只读文件，无副作用、无网络调用（LLM review 钩子见 §7）。

## 6. 发布门禁语义

已确认的默认值（`core/config.py`）：`block_on = ["critical", "high"]`、`min_confidence = 0.80`、`require_quality_label = "VERIFIED"`。已确认的调度事实（`cli/argus.py`）：`_required_for_snapshot` 把 `code` 计入 required（有源码文件即 required），`_agent_result` 对所有 agent 设 `required=True` → **code agent 失败（未 completed）时 `expected_required - completed` 非空，gate = `unknown`（fail-closed）**。这是现有行为、P3 正确，本 spec 不改动。

- 维护性 finding 严重度 low/medium，永不命中 `block_on` → 永不 `block`。**若未来某 finding 命中 block_on，必须显式复核**——v1 规则集无 critical/high。
- **`min_confidence = 0.80` 的直接后果**：置信 <0.80 的 finding（CODE-104=0.75、CODE-106=0.70、CODE-109=0.60、CODE-110=0.70）在 `evaluate_policy` 里会被 `confidence < min_confidence` 直接跳过——**连 verified warning 都进不了**。它们仍出现在 AgentResult.findings 与报告里，但既不 warn 也不 block。可接受：这些是启发式，低置信不打扰门禁。
- **`warn` gate 由 ≥0.80 置信的 medium finding 撑起**（CODE-103=0.80、CODE-105=0.80、CODE-107=0.85、CODE-108=0.85）。`simple-maintainability` 的 `expected_gate=warn` 依赖它们——评测 fixture 必须保证至少命中其中一条，且只命中 ground-truth 列出的那些（见 §9）。
- **规则引擎必须防御性**：code 是 required agent，规则集新增的解析代码不能引入崩溃路径（否则一个规则 bug 会把 gate 打成 unknown）。`scan_path` 对每个文件包 try/except，规则异常 → 跳过该文件，不 abort 整个 agent。

## 7. LLM review 钩子（沿用，非阻塞）

skill 侧沿用 `argus-code-rule-scan` 的 `_llm_review_findings`（`skills/_shared/llm_review.py`）：agentteams 模式下 LLM 可对确定性 finding 复核、抑制 FP（verdict NO → confidence×0.3 + `llm_suppressed`）。本地引擎无 LLM，规则本身必须自足（FP guard 是主防线，LLM 是辅助）。这保证两引擎结果可用但 local 不依赖 LLM。

## 8. 推迟清单（明确不做，留第二轮）

| 信号 | 文档出处 | 推迟原因 |
|---|---|---|
| god-function 职责判断（同时查询/计算/更新/通知） | §14.3 | 语义判断，规则化 FP 高 |
| 命名质量全量 | §1.1 | 除单字母参数外需语义 |
| 无约束字典（字段随意变化） | §8.1 | 需类型/调用点分析，FP 高 |
| 跨文件重复业务条件 | §14.2 | 需相似度引擎 |
| 手写去重/成员判断循环 | §14.1 | 与 CODE-108 重叠但需值分析 |
| 非法状态可表示（类型压缩状态空间） | §10 | 需类型系统分析，超出静态规则 |
| 重复分组/排序/建索引（跨调用点） | §14.1 | 需跨函数数据流 |
| 注释/意图/错误信息质量 | §3.2/§2.1 | LLM 判断 |
| JS/TS/Java/Go/Rust 的结构化规则 | — | v2 语言扩展 |

## 9. 评测集成

- **新增场景 `simple-maintainability`**（category: simple）：
  - `demo/eval/simple/simple-maintainability/src/app/pricing.py`：人为植入确定性信号——长函数（CODE-101）、魔法折扣率 `* 0.8`（CODE-104）、裸字符串状态 `== "pending"`（CODE-105）、映射 if/elif 链（CODE-107）、OR 链（CODE-108）。
  - `ground-truth.json`：`expected_findings` 只标**高置信规则**（101/104/105/107/108），不标启发式（103/106/109/110/111）。
  - **fixture 工程约束**：`pricing.py` 必须保证**只触发 ground-truth 列出的那 5 条**，不触发任何其他 `code.*` finding——否则 precision<1，`full_match` 失败。具体：函数体 ≤100 行（不触发 101 之外无问题）、嵌套深度 <4（避免 103 触发）、同一函数内布尔互斥标志 <3（避免 106）、无平行数组/双层 join/单字母参数（避免 109/110/111）。评测场景测试必须断言：fixture 上恰好只有 5 条 finding。
  - `expected_gate: warn`（由 105/107/108 中 ≥0.80 置信的 medium finding 撑起，见 §6）。
- **零误报 guard**：现有 `simple-clean`（expected_findings=[]）继续要求全部 assessor 零 finding——若新规则在干净代码上 FP，`simple-clean` 会变 DIFF，即误报防线。
- **manifest.json**：登记 `{"id": "simple-maintainability", "category": "simple", "path": "simple/simple-maintainability"}`。
- **gate 重 pin**：manifest + 新 ground-truth 改变 eval_fingerprint → `python demo/eval/gate.py --pin --force`（先跑本地引擎全量评测确认无回归）。注意 agentteams 评测 + `--token-cost` 基线不重建（本地基线即可，成本门禁默认关闭）。

## 10. 测试策略

| 层 | 测试 | 内容 |
|---|---|---|
| 规则单元 | `tests/unit/test_code_maintainability.py` | 11 条规则各 +/− case（每条 ≥2 例）；FP guard 反向 case（干净代码不报） |
| parity | 同上文件内 | 同语料 → skill adapter vs 本地 detector 产出 `(category, file, line)` 集合一致 |
| 集成 | 沿用 `test_code_detector.py` 风格 | `CodeDetector().detect()` 对含维护性信号 fixture 出 finding；干净 fixture 空 |
| skill | `tests/unit/test_maintainability_skill.py` | `implementation/main.py` `--input`/`--output` 往返、schema 校验、失败 exit 2 |
| 评测 | harness 跑 `simple-maintainability` + `simple-clean` | full_match / 零误报；全量 8+1 场景回归 |

验收：`pytest tests/unit/` 全绿；`python demo/eval/harness.py --engine local` 无审计错误，新场景 MATCH，既有场景不回归；`gate.py` 对比不回归可推进 pin。

## 11. 文件地图

**新增**
- `skills/argus-code-maintainability-scan/SKILL.md` — 规则 + P4「禁止」条款
- `skills/argus-code-maintainability-scan/manifest.yaml` — 镜像 `argus-code-rule-scan`（assessor / `python3 implementation/main.py` / input/output json-file / permissions: snapshot.read, own_task_artifact.write / network: true / idempotency: input_digest）
- `skills/argus-code-maintainability-scan/implementation/rules.py` — **规则引擎（纯 stdlib）**
- `skills/argus-code-maintainability-scan/implementation/main.py` — standalone adapter
- `skills/argus-code-maintainability-scan/schemas/{input,output,error}.schema.json`
- `agents/code/maintainability.py` — host 侧适配（调 rules.scan_path → Finding），或并入 detector.py
- `demo/eval/simple/simple-maintainability/src/app/pricing.py`
- `demo/eval/simple/simple-maintainability/ground-truth.json`
- `tests/unit/test_code_maintainability.py`
- `tests/unit/test_maintainability_skill.py`

**修改**
- `agents/code/detector.py` — 接入维护性规则（保留 placeholder 逻辑）
- `agents/code/identity.yaml` — capabilities 加 `maintainability_scan`，optional_skills 加 `argus-code-maintainability-scan`
- `skills/skills.lock.json` — `argus-code` assignments 加 `argus-code-maintainability-scan`（version 0.0.1 + sha256，随 publish_nacos 发布）
- `demo/eval/manifest.json` — 登记新场景
- `demo/eval/README.md` — 场景清单加一行（可选）

**不修改**：`core/scheduler.py`（code 已按 .py 路由）、`core/policy.py`（维护性不 block）、`cli/argus.py`（detector 已按 agent=code 调 CodeDetector）。

## 12. 验收清单

- [ ] 11 条规则单测全绿（含 FP guard 反向 case）
- [ ] parity 测试：skill vs 本地 detector 同语料一致
- [ ] `simple-maintainability` harness MATCH（full_match + gate=warn）
- [ ] `simple-clean` 不回归（零误报）
- [ ] 全量 pytest 无失败
- [ ] `gate.py --pin --force` 重 pin 成功、门禁对比通过
- [ ] skill 发布到 Nacos（`publish_nacos.py`）后 `argus-code` worker assignments 含新 skill
- [ ] P4：抽查 finding 无源码正文，evidence 只含脱敏摘录 + hmac
