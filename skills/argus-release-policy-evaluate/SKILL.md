---
name: argus-release-policy-evaluate
description: Deterministic argus-release-policy-evaluate Skill for the Argus audit pipeline.
---

# argus-release-policy-evaluate

基于 MetaDecision 和 policy 配置计算确定性 `release_gate`。

## 输入

已调度 AgentResult、MetaDecision、block_on、min_confidence、incomplete_run。

## 输出

PolicyDecision：`pass|warn|block|unknown`、原因、verified/blocking finding IDs。

## 禁止

不得调用 LLM 自由决定 gate；不得升级 Meta label；不得忽略 required Agent 失败；不得把 attack verdict 当 release gate。

## Execution

Run by the AgentTeams typed-Task executor as:

```bash
python implementation/main.py --input <json> --output <json>
```

- Exit 0 with a schema-valid output on success; exit 2 with a schema-valid error artifact on invalid input.
- No imports from host `core.*`, `agents.*`, or `agentteams.*`.
