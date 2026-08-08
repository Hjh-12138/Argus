---
name: argus-code-rule-scan
description: Deterministic headless assessor that scans the immutable source snapshot and emits schema-valid findings.
---

# argus-code-rule-scan

Reads a JSON input (snapshot file inventory plus role-specific fixtures), scans
the source under `source_root`, and writes a schema-valid AgentResult. It is
executed by the AgentTeams typed-Task executor as:

```bash
python implementation/main.py --input <json> --output <json>
```

## Rules

- Only read files under the declared `source_root`; never execute target code.
- Findings reference snapshot paths and carry the snapshot file SHA-256.
- Raw secrets never appear in findings; security output stores only redacted
  display and HMAC tokens.
- On invalid input, write the error artifact and exit 2.

## 禁止

- 禁止执行目标代码、安装依赖或改动目标工作区。
- 禁止在网络调用或输出中泄漏源码、secret 或原始推理。
- 禁止把 registry 缺失/超时误判为"依赖不存在"。
- 禁止绕过 snapshot digest、deadline 或 idempotency 校验。
- 禁止在命令失败时输出原始 stderr、源码或 secret。
