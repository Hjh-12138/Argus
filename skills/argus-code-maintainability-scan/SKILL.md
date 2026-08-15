---
name: argus-code-maintainability-scan
description: Deterministic headless assessor that scans the immutable source snapshot for code maintainability smells and emits schema-valid findings.
---

# argus-code-maintainability-scan

Reads a JSON input (snapshot file inventory), scans Python source under
`source_root`, and writes a schema-valid AgentResult. It is executed by the
AgentTeams typed-Task executor as:

```bash
python implementation/main.py --input <json> --output <json>
```

## Rules

- CODE-101 function_length / CODE-102 too_many_params / CODE-111 single_letter_param
- CODE-103 deep_nesting / CODE-106 boolean_state_flags
- CODE-104 magic_number / CODE-105 bare_string_enum
- CODE-107 mapping_if_chain / CODE-108 or_chain_membership
- CODE-109 parallel_arrays / CODE-110 linear_scan_no_index

## Constraints

- Only read files under the declared `source_root`; never execute target code.
- Findings reference snapshot paths and carry the snapshot file SHA-256.
- Raw source body never appears in findings; output stores only redacted
  display and HMAC tokens (P4).
- On invalid input, write the error artifact and exit 2.

## 禁止

- 禁止执行目标代码、安装依赖或改动目标工作区。
- 禁止在网络调用或输出中泄漏源码、secret 或原始推理。
- 禁止在命令失败时输出原始 stderr、源码或 secret。
- 禁止让规则解析异常导致 agent 失败（单文件异常跳过该文件）。
