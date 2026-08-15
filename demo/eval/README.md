# Argus 评测集（Evaluation Benchmark）

> R0.4 —— 为 R5.1 评测 harness 提供**独立标注**的标准任务集。
> 覆盖「简单 / 复杂 / 异常」三类场景，每个场景 = 一个被审目标 + 一份 ground truth。

## 为什么要有这份评测集

路线图核心原则 P5「独立验证不可自评」：评测的判据必须独立于被验证者。
如果评测用「Meta 说对就对」当标准答案，那 Meta 既是考生又是考官，它的 bug 永远测不出来。

所以每个场景的 `ground-truth.json` 是**人标注的缺陷语义**（真实世界里「这里错了」），
与 Argus / MetaReviewer / detector 的输出完全无关。评测 harness 跑完 Argus 后，
把 Argus 的 findings 与 ground truth 对齐，用独立判据算质量。

## 三类场景

| 类别 | 目的 | 例子 |
|---|---|---|
| `simple` | 隔离测单个 detector 的召回/漏报 | 单个 SQL 注入、单个硬编码密钥、干净代码 |
| `complex` | 测多 agent 协作 + 多缺陷交叉 | 一个含 5 个缺陷（跨 sec/dep/code/delivery）的 web app |
| `abnormal` | 测边界/异常/误报抑制 | 仅文档变更、占位密钥、二进制文件、空目标 |

## 目录结构

```
demo/eval/
├── README.md                 # 本文件
├── manifest.json             # 场景索引（harness 用）
├── harness.py                # R5.1 评测 harness（见「R5.1 评测 harness」）
├── gate.py                   # R5.2 版本 pin + 评测门禁（见「R5.2 …」）
├── eval.lock.json            # R5.2 pin 文件（版本指纹 + 基线 + 权重）
├── simple/
│   └── simple-sqli/
│       ├── src/              # 被审目标（argus audit --target 指向这里）
│       │   └── app/search.py
│       └── ground-truth.json
├── complex/
│   └── complex-webapp/
│       ├── src/...
│       ├── registry-fixture.json   # 依赖场景专用
│       └── ground-truth.json
└── abnormal/
    └── ...
```

- `src/` 是被审代码。harness 跑 `argus audit --target <场景>/src`。
  注意被审目录**不能叫 `target`**——`core/snapshot.py` 的 `_SKIP_DIR_PARTS` 含 `"target"`，
  会整目录跳过（demo 用 `vulnerable/`/`fixed/` 规避，评测集统一用 `src/`）。
- `registry-fixture.json` 给 `dep` detector 提供存在性证据（`--registry-fixture` 传入）。
- `ground-truth.json` 是独立标注的标准答案（见下）。

## ground-truth 格式（schema v1）

```json
{
  "schema_version": "1",
  "scenario_id": "simple-sqli",
  "category": "simple",               // simple | complex | abnormal
  "title": "Single SQL injection",
  "description": "一个 SQL 查询拼接了未过滤用户输入",
  "expected_gate": "block",           // pass | warn | block | unknown
  "expected_findings": [
    {
      "key": "sqli-1",                 // 语义键，独立于 detector 的 id/fingerprint
      "agent": "sec",
      "category": "security.sql_injection",
      "severity": "critical",
      "file": "app/search.py",
      "line_start": 2,
      "line_end": 2,
      "cwe": "CWE-89",
      "title": "SQL query concatenates untrusted input"
    }
  ],
  "annotation": {
    "annotator": "human-review",
    "independent_of": "meta-detector",
    "notes": "ground truth 由人标注缺陷语义，不依赖 Argus/Meta 输出（P5）。"
  }
}
```

### 对齐（matching）约定

harness 判断「Argus 找到的 finding」是否命中 ground truth 时，用**语义键**
`(agent, category, file, line_start)` 对齐，**不用** detector 生成的 `id`/`fingerprint`——
后者是 detector 的实现细节，若用于判据就等于让 detector 给自己出题。

- **召回（recall）**：ground truth 里的每个 finding 是否被 Argus 找到（按语义键）。
- **精确（precision）**：Argus 报告的每个 finding 是否在 ground truth 里（`expected_findings` 为空的场景即纯精确测试）。
- **gate 一致性**：`expected_gate` vs Argus 实际 gate。

## 场景清单

| scenario_id | 类别 | 缺陷数 | expected_gate | 测什么 |
|---|---|---|---|---|
| simple-sqli | simple | 1 | block | sec 召回 SQL 注入 |
| simple-secret | simple | 1 | block | sec 召回硬编码密钥 |
| simple-clean | simple | 0 | pass | 零误报 |
| simple-maintainability | simple | 5 | warn | code 召回可维护性信号（长函数/魔法数字/裸字符串枚举/映射链/or链） |
| complex-webapp | complex | 5 | block | 四 agent 协作 + 多缺陷交叉 |
| abnormal-doc-only | abnormal | 0 | pass | doc-only 变更有意跳过 |
| abnormal-secret-placeholder | abnormal | 0 | pass | 占位密钥不误报 |
| abnormal-binary | abnormal | 0 | pass | 二进制文件被快照跳过 |
| abnormal-empty | abnormal | 0 | unknown | 空目标不应真空 pass（fail-closed） |

## R5.1 评测 harness

`harness.py` 消费本评测集：读 `manifest.json` -> 每个场景跑 N 次
`argus audit` -> 按语义键对齐 ground truth -> 算 recall / precision / gate 一致性。

```bash
python demo/eval/harness.py                             # 全量 3 次（默认 --engine local）
python demo/eval/harness.py --runs 1 --only complex-webapp
python demo/eval/harness.py --engine agentteams --runs 5   # 非确定性引擎（需 AgentTeams 环境）
python demo/eval/harness.py --strict --json-out demo/eval/last-run.json
```

选项：`--runs N`（每场景 audit 次数）、`--only id1,id2`（场景过滤）、
`--engine local|agentteams`、`--json-out <path>`（落完整结果）、`--strict`（门禁）。

- **隔离**：每次 audit 在临时目录跑（cwd=临时目录、PYTHONPATH=项目根），
  不污染项目根的 `.argus/state.db` 与 reports。
- **对齐**：语义键 `(agent, category, file, line_start)`（见上）。跨 N 次 run 按
  语义键去重——同一 finding 在多次 run 重复报告，不重复计 FP。
- **recall**：每个 ground-truth finding 是否被至少一次 run 找到。
- **precision**：Argus 报告的每个 distinct finding 是否在 ground truth 里。
- **gate 一致性**：全部 N 次 run 的 `release_gate` 都等于 `expected_gate`；
  有 run 出错即视为不一致（fail-closed，错误不算 pass）。
- **退出码**：0 = 无审计错误；1 = 有审计错误（subprocess 失败 / report 缺失 /
  不可解析）；`--strict` 下任一场景未完全命中（gate 不一致 / recall<1 / precision<1）
  也返回 1。
- **输出**：每场景一行 verdict（MATCH/DIFF）+ recall/precision/FP/缺失语义键，
  末尾 SUMMARY 汇总（full_match、gate_consistent、audit_errors、macro recall/precision）。

实测（本地引擎，R0.4 同一结论）：6/8 full_match；complex-webapp recall 0.80
（漏 `app/auth.py:1` = SECRET_TOKEN 词边界 bug）；abnormal-empty gate DIFF
（真空 pass）。两项均为待修的已知缺口，评测集按真实语义标注、不迁就。

## R5.2 版本 pin + 评测门禁

`gate.py` 把评测结果 pin 进 `eval.lock.json`，变更后跑评测与 pin 的基线对比，
**任一场景回归即拒绝**，达阈值才允许推进 pin（升版本）——复用 `contract.lock.json`
/ `skills.lock.json` 的 lock 机制。

```bash
python demo/eval/gate.py --pin          # 建立基线（无 pin 时）；门禁通过后推进 pin
python demo/eval/gate.py                # 对现有 pin 跑门禁（默认，不写文件）
python demo/eval/gate.py --json cur.json   # 消费 harness --json-out 的报告，不重跑
python demo/eval/gate.py --pin --force  # 门禁未过仍强制推进（显式知情，慎用）
python demo/eval/harness.py --token-cost --gateway-container agentteams-controller \
    --json-out cur.json                 # agentteams 评测并记录每场景 token 差分成本
python demo/eval/gate.py --json cur.json --max-cost-ratio 1.2  # 成本预算门禁
```

`eval.lock.json` 记录：`argus_version`（git 短 SHA）、`engine_fingerprint`
（core/agents/cli/agentteams 内容摘要）、`eval_fingerprint`（manifest + 全部
ground-truth 内容摘要）、`weights`（D3 权重）、`baseline`（完整评测报告）。

- **pin 机制**：`eval_fingerprint` 一变（ground truth / manifest 改）即视为测量
  基准变了，门禁拒绝并提示重 pin——不能拿旧基线比新评测集。dot 目录（如副本/
  临时产物）不计入指纹。
- **判据**（全部满足才过）：
  1. 审计无错误（fail-closed）；
  2. 覆盖不缩水：基线场景必须都在，新场景必须 full_match；
  3. 逐场景不回归：recall / precision / gate 一致性只许持平或变好
     （已知 DIFF 保持 DIFF 不算回归）；
  4. 加权复合分 `w_r·recall_macro + w_p·precision_macro + w_g·gate_ratio`
     ≥ 基线（D3 质量）；
  5. token 成本 ≤ 基线 × `--max-cost-ratio`（D3 成本维度，默认不查；
     数据来自 harness `--token-cost`，双方都缺则 fail-closed）。
- **token 成本**：agentteams 评测时 harness 在每场景 audit 前后对 AI 网关
  （Higress ai-statistics）的累计 token 计数做差分，记入场景 `tokens.total_delta`；
  门禁 `--max-cost-ratio` 用它做预算检查（`--token-cost` + `--gateway-container`
  取数，见 `agentteams/gateway_metrics.py`）。
- **退出码**：0 = 通过（且 `--pin` 时已推进）；1 = 未通过（回归 / 未达阈值 /
  审计错误 / 评测集变更需重 pin）；2 = 无 pin 且未 `--pin`；3 = 输入/配置错误。
- **权重**：默认 1/1/1（无加权，逐场景不回归即过）；`--weight-recall` 等调权后
  允许跨场景权衡，`--pin` 把生效权重固化进 lock。

基线实测（本地引擎）：`argus_version=a6ae5cb`，8 场景 6 full_match、7
gate_consistent、recall_macro 0.975、precision_macro 1.00——如实记录两个已知
缺口，门禁对当前代码可通过；修复任一缺口后 recall 上升即可 `--pin` 推进基线。

## 已知缺口（评测集应当暴露、而非迁就）

评测集按**真实语义**标注，不迁就当前 Argus 的实现。以下缺口会被评测集正确判为「未命中」，
是需要修的 bug，不是评测集的错：

1. **调度路由盲区**：SQL 注入若写在 `app.py`（路径不含 `search/query/auth/middleware`），
   当前 `scheduler.py` 不会把 `sec` 派到该文件 → 漏报。评测集简单场景用 `app/search.py` 等
   自然路径避免歧义，但真实世界里这仍是 gap，留给后续调度器改进。
2. **空目标真空 pass**：`abnormal-empty` 当前 Argus 返回 `pass`（fail-open），
   评测集标注 `unknown`（fail-closed）——这是需要修的设计缺陷。
3. **dep 行号粒度**：dep detector 的 finding 固定 `line_start=1`（指向整个 manifest），
   不是具体依赖行。ground truth 与之一致（line 1），但行号精度本身是已知局限。
4. **secret 正则词边界漏报（complex-webapp 实测暴露）**：`HARDCODED_SECRET` 用
   `\b(api[_-]?key|secret|token|password)\b`，词边界让 `SECRET_TOKEN`/`SECRET_KEY` 这类
   常见变量名**完全匹配不到**（下划线是词字符，`secret`/`token` 都不独立成词）。
   实测：`API_KEY=…` 命中、`SECRET=…`/`TOKEN=…` 命中、`SECRET_TOKEN=…` 漏报。
   complex-webapp 的 ground truth 保留 `SECRET_TOKEN`（真实语义就是硬编码凭据），
   当前 Argus 对该场景召回 4/5——这是待修的 detector bug。

## 待拍板（路线图 D2 / D3）

- **D2 ground truth 由谁终审**：本评测集初版由 `human-review`（本会话人工标注）产出，
  正式验收前应由独立 reviewer（非 Meta、非 detector 作者）复核签认——这是 P5 成立的前提。
- **D3 质量/成本权重**：R5.2 门禁已实现可配置权重（默认 1/1/1 = 逐场景不回归，
  `--weight-*` 调权后允许跨场景权衡，`--pin` 固化生效权重）。「质量 vs 成本 vs
  耗时」里的**成本/耗时维度仍未纳入**（R4.2 观测层被跳过）——若以后要「成本+30%
  除非质量+15% 否则不接受」这类权衡，需在评测里补 token/耗时指标再配权重。
