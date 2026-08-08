---
name: argus-evidence-verify
description: Independently verify Finding path, line, hash, evidence, and actionability
---
# argus-evidence-verify

独立验证 Agent finding 的 path、line、source hash、evidence 与 actionability，输出 `MetaDecision`。

## 调用条件

每个已调度 assessor 的 `AgentResult` 完成后调用；所有 Agent 终态后再做 consistency pass。

## 决策标签

- `VERIFIED`：路径、行号、哈希、证据和可执行性通过；
- `NEEDS_EVIDENCE`：可能成立但证据不足；
- `INCONSISTENT`：与其他 finding 或快照事实冲突；
- `HALLUCINATION`：引用对象不存在或与快照冲突；
- `NOT_ACTIONABLE`：缺少可执行 remediation/verification。

## 禁止条件

不得创建新 finding、改原事实/severity、补造证据或写 release gate。
