# Argus Code 可维护性审查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Argus 的 `code` agent 补上设计时欠的可维护性审查——11 条确定性规则，本地引擎与 AgentTeams skill 同步落地，产出 advisory finding（只 warn 不 block）。

**Architecture:** 规则实现为纯 stdlib 模块 `skills/argus-code-maintainability-scan/implementation/rules.py`（`scan_path(path, text) -> list[RuleHit]`），skill adapter 与本地 detector 两侧共用同一规则模块，配 parity 测试防漂移。本地引擎在 `CodeDetector.detect()` 里追加维护性 finding；agentteams 走新 skill `argus-code-maintainability-scan` 挂到 `argus-code` worker。评测新增 `simple-maintainability` 场景。

**Tech Stack:** Python 3.13, pytest, 现有 Argus core（`core/schemas.py`/`core/redaction.py`/`core/meta.py`/`core/policy.py`），skill 协议（manifest.yaml + SKILL.md + schemas + standalone main.py）。

**Spec:** `docs/superpowers/specs/2026-08-15-argus-code-maintainability-design.md`（本计划从 spec 论证，executor 需先读 spec + 本文档）

## Global Constraints

- **不提交 git**：本计划所有任务**不执行 `git commit`**（用户已明确「不提交git」）。如需版本管理，另行提出后再加 commit 步骤。
- **v1 仅 Python**：所有规则只扫描 `.py`；`.js/.ts/.java/.go/.rs` 统一留 v2（spec §3.3）。
- **规则引擎纯 stdlib、防御性**：`rules.py` 不得 import 任何 host 模块；`scan_path` 对每个文件/每条规则包 try/except，规则异常 → 跳过该文件，**绝不使 `code` agent 失败**（code 是 required agent，失败会把 gate 打成 unknown，P3 fail-closed 但不应因规则 bug 触发）。
- **P4**：finding 只存脱敏 excerpt + hmac fingerprint，源码正文永不进入 finding（复用 `core/redaction.redact`/`hmac_fingerprint` 与 skill 侧 `_redact`/`_fingerprint`）。
- **严重度**：全部 low/medium；`block_on=["critical","high"]` → 永不 block。`min_confidence=0.80`：置信 <0.80（CODE-106=0.7/109=0.6/110=0.7/104=0.75）不进 verified warning，仍出现在 findings 里。
- **skill 必须满足 contract 测试**（`tests/contract/test_skill_contracts.py`）：manifest.yaml + SKILL.md（含「禁止」）+ `schemas/{input,output,error}.schema.json`（type object + `additionalProperties: false`）+ `implementation/main.py`。
- **skill standalone**：`implementation/main.py` 无 host import（可 import 同目录 `rules` 与 `_shared/llm_review`）。
- 现有 `pytest tests/unit tests/contract` 必须保持全绿；`demo/eval/` 场景不回归。

---

## File Map

**新增**
- `skills/argus-code-maintainability-scan/implementation/rules.py` — **规则引擎（纯 stdlib）**
- `skills/argus-code-maintainability-scan/implementation/main.py` — standalone skill adapter
- `skills/argus-code-maintainability-scan/SKILL.md` — 规则 + P4「禁止」条款
- `skills/argus-code-maintainability-scan/manifest.yaml`
- `skills/argus-code-maintainability-scan/schemas/input.schema.json`
- `skills/argus-code-maintainability-scan/schemas/output.schema.json`
- `skills/argus-code-maintainability-scan/schemas/error.schema.json`
- `agents/code/maintainability.py` — host 侧适配（RuleHit → Finding）
- `demo/eval/simple/simple-maintainability/src/app/pricing.py` — 评测 fixture
- `demo/eval/simple/simple-maintainability/ground-truth.json`
- `tests/unit/test_code_maintainability.py` — 规则单测（直接测 rules.scan_path）
- `tests/unit/test_maintainability_skill.py` — skill 单测 + parity 测试

**修改**
- `agents/code/detector.py` — `CodeDetector.detect()` 追加维护性 finding
- `agents/code/identity.yaml` — capabilities 加 `maintainability_scan`、optional_skills 加 `argus-code-maintainability-scan`
- `skills/skills.lock.json` — 登记新 skill + `argus-code` assignments 追加
- `demo/eval/manifest.json` — 登记 `simple-maintainability`
- `demo/eval/README.md` — 场景清单加一行

---

### Task 1: rules.py 骨架 + 结构规则（101 function_length / 102 too_many_params / 111 single_letter_param）

**Files:**
- Create: `skills/argus-code-maintainability-scan/implementation/rules.py`
- Create: `tests/unit/test_code_maintainability.py`

**Interfaces:**
- Produces（后续所有任务依赖）:
  - `@dataclass(frozen=True) class RuleHit`: 字段 `rule_id, category, severity, confidence, line_start, line_end, title, detail, remediation, excerpt`（全部 str/float/int）
  - `def scan_path(path: str, text: str) -> list[RuleHit]` — 只对 `.py` 运行；顺序按 `(line_start, rule_id)` 排序；永不 raise
  - 常量 `_FUNCTION_LENGTH_LIMIT=100`, `_PARAM_LIMIT=6`, `_NEST_DEPTH_LIMIT=4`, `_MAGIC_WHITELIST={0,1,-1,2}`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_code_maintainability.py`（本任务只测 101/102/111）：
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "argus-code-maintainability-scan" / "implementation"))
from rules import scan_path


def _hits(text):
    return scan_path("app/a.py", text)


def test_101_long_function_detected():
    text = "def long_fn():\n" + "".join(f"    x = x + {i % 3}\n" for i in range(105))
    assert any(h.rule_id == "CODE-101" for h in _hits(text))


def test_101_short_function_ok():
    assert not any(h.rule_id == "CODE-101" for h in _hits("def f():\n    return 1\n"))


def test_102_too_many_params_detected():
    assert any(h.rule_id == "CODE-102"
               for h in _hits("def f(a, b, c, d, e, g, h):\n    return a\n"))


def test_102_params_within_limit_ok():
    assert not any(h.rule_id == "CODE-102"
                   for h in _hits("def f(a, b, c, d, e, g):\n    return a\n"))


def test_111_single_letter_param_detected():
    assert any(h.rule_id == "CODE-111" for h in _hits("def f(x, y):\n    return x\n"))


def test_111_descriptive_params_ok():
    assert not any(h.rule_id == "CODE-111"
                   for h in _hits("def apply(amount, rate):\n    return amount\n"))


def test_scan_path_ignores_non_python():
    assert scan_path("app/app.js", "const x = 1;\n") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rules'`

- [ ] **Step 3: 写最小实现**

`skills/argus-code-maintainability-scan/implementation/rules.py`：
```python
"""Argus code maintainability rules (pure stdlib, no host imports).

v1 targets Python (.py) only. Every rule is a pure function over a file's
lines and returns RuleHit tuples. scan_path() never raises: a rule that
throws is skipped so one rule bug cannot fail the whole agent (code is a
required auditor). Findings carry a redacted excerpt only — no source body
leaves this module (P4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FUNCTION_LENGTH_LIMIT = 100
_PARAM_LIMIT = 6
_NEST_DEPTH_LIMIT = 4
_MAGIC_WHITELIST = {0, 1, -1, 2}

_DEF_RE = re.compile(r"^(\s*)def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:\s*(#.*)?$")
_INDENT = re.compile(r"^(\s*)")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?([^'\"\s,]{6,})"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(ghp_[A-Za-z0-9]{20,})\b"),
]


def _redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("***", out)
    return out


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    category: str
    severity: str
    confidence: float
    line_start: int
    line_end: int
    title: str
    detail: str
    remediation: str
    excerpt: str


def _hit(rule_id, category, severity, confidence, line_start, line_end,
         title, detail, remediation, line_text) -> RuleHit:
    return RuleHit(rule_id=rule_id, category=category, severity=severity,
                   confidence=confidence, line_start=line_start, line_end=line_end,
                   title=title, detail=detail, remediation=remediation,
                   excerpt=_redact(line_text.strip()[:300]))


def _rule_function_length(lines):
    hits = []
    for i, line in enumerate(lines):
        m = _DEF_RE.match(line)
        if not m:
            continue
        def_indent = len(m.group(1))
        j = i + 1
        body_count = 0
        while j < len(lines):
            raw = lines[j]
            if not raw.strip():
                j += 1
                continue
            indent = len(_INDENT.match(raw).group(1))
            if indent <= def_indent:
                break
            if not raw.strip().startswith("#"):
                body_count += 1
            j += 1
        if body_count > _FUNCTION_LENGTH_LIMIT:
            hits.append(_hit(
                "CODE-101", "code.function_length", "low", 0.85, i + 1, i + 1,
                f"Function '{m.group(2)}' body has {body_count} non-blank lines "
                f"(> {_FUNCTION_LENGTH_LIMIT})",
                "Long function accumulates divergent responsibilities",
                "拆分长函数：按职责拆成语义明确的子步骤，保持单一职责",
                line))
    return hits


def _rule_too_many_params(lines):
    hits = []
    for i, line in enumerate(lines):
        m = _DEF_RE.match(line)
        if not m:
            continue
        raw = m.group(3)
        if not raw.strip():
            continue
        params = [p.strip() for p in raw.split(",") if p.strip()]
        params = [p for p in params
                  if p not in ("self", "cls") and not p.startswith("*")]
        if len(params) > _PARAM_LIMIT:
            hits.append(_hit(
                "CODE-102", "code.too_many_params", "low", 0.9, i + 1, i + 1,
                f"Function '{m.group(2)}' takes {len(params)} parameters "
                f"(limit {_PARAM_LIMIT})",
                "Parameter list keeps growing as responsibilities accumulate",
                "成组且增长的参数收敛为明确的业务对象", line))
    return hits


def _rule_single_letter_param(lines):
    hits = []
    for i, line in enumerate(lines):
        m = _DEF_RE.match(line)
        if not m:
            continue
        for p in (p.strip() for p in m.group(3).split(",") if p.strip()):
            if p in ("self", "cls"):
                continue
            if re.fullmatch(r"[a-z]", p):
                hits.append(_hit(
                    "CODE-111", "code.single_letter_param", "low", 0.9, i + 1, i + 1,
                    f"Function '{m.group(2)}' uses single-letter parameter '{p}'",
                    "Parameter name carries no business meaning",
                    "参数名表达业务含义，而不是让读者猜测", line))
                break
    return hits


def scan_path(path, text):
    if not path.endswith(".py"):
        return []
    lines = text.splitlines()
    rules = (_rule_function_length, _rule_too_many_params, _rule_single_letter_param)
    hits = []
    for rule in rules:
        try:
            hits.extend(rule(lines))
        except Exception:
            continue  # a rule bug must not fail the required code auditor
    hits.sort(key=lambda h: (h.line_start, h.rule_id))
    return hits
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: 7 passed

---

### Task 2: rules.py 嵌套与状态规则（103 deep_nesting / 106 boolean_state_flags）

**Files:**
- Modify: `skills/argus-code-maintainability-scan/implementation/rules.py`
- Modify: `tests/unit/test_code_maintainability.py`

**Interfaces:**
- Consumes: Task 1 的 `_DEF_RE`/`_INDENT`/`_hit`/`scan_path`
- Produces: `scan_path` 增补 103/106 两条规则

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/test_code_maintainability.py`）
```python
def test_103_deep_nesting_detected():
    text = ("if a:\n"
            "    if b:\n"
            "        if c:\n"
            "            if d:\n"
            "                return 1\n"
            "    return 0\n")
    assert any(h.rule_id == "CODE-103" for h in _hits(text))


def test_103_shallow_nesting_ok():
    text = "if a:\n    if b:\n        return 1\nreturn 0\n"
    assert not any(h.rule_id == "CODE-103" for h in _hits(text))


def test_106_three_bool_flags_detected():
    text = ("def run():\n"
            "    is_started = True\n"
            "    is_processing = False\n"
            "    is_finished = False\n"
            "    return 0\n")
    assert any(h.rule_id == "CODE-106" for h in _hits(text))


def test_106_two_bool_flags_ok():
    text = ("def run():\n"
            "    is_started = True\n"
            "    is_finished = False\n"
            "    return 0\n")
    assert not any(h.rule_id == "CODE-106" for h in _hits(text))
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: 新增 4 条 FAIL（无 CODE-103/106）

- [ ] **Step 3: 实现**（在 `rules.py` 顶部加 `_CONTROL_RE`、`_BOOL_FLAG_RE`，加两个规则函数，并注册进 `scan_path`）
```python
_CONTROL_RE = re.compile(r"^(if|elif|for|while|with|try|except|def)\b")
_BOOL_FLAG_RE = re.compile(r"^\s*(is|has|can)_[A-Za-z0-9_]+\s*=\s*(True|False)\b")


def _rule_deep_nesting(lines):
    stack = []  # (indent, is_control)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(_INDENT.match(line).group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if _CONTROL_RE.match(stripped) and line.rstrip().endswith(":"):
            open_controls = sum(1 for _, c in stack if c)
            if open_controls + 1 >= _NEST_DEPTH_LIMIT:
                return [_hit(
                    "CODE-103", "code.deep_nesting", "medium", 0.8, i + 1, i + 1,
                    f"Control-flow nesting depth reaches {_NEST_DEPTH_LIMIT}",
                    "Deeply nested control flow hides branches from the reader",
                    "用早返回/拆函数降低嵌套深度，保持控制流简单", line)]
            stack.append((indent, True))
        else:
            stack.append((indent, False))
    return []


def _rule_boolean_state_flags(lines):
    cur_indent = None
    flags = set()
    for i, line in enumerate(lines):
        m = _DEF_RE.match(line)
        if m:
            cur_indent = len(m.group(1))
            flags = set()
            continue
        if not line.strip():
            continue
        indent = len(_INDENT.match(line).group(1))
        if cur_indent is not None and indent <= cur_indent:
            cur_indent = None
            flags = set()
            continue
        bm = _BOOL_FLAG_RE.match(line)
        if bm and cur_indent is not None:
            flags.add(bm.group(0).split("=")[0].strip())
            if len(flags) >= 3:
                return [_hit(
                    "CODE-106", "code.boolean_state_flags", "medium", 0.7, i + 1, i + 1,
                    "3+ boolean state flags in one function suggest a hidden state machine",
                    f"flags: {sorted(flags)}",
                    "互斥状态用枚举/状态机表达，而不是多个布尔标志", line)]
    return []
```
`scan_path` 的 `rules` 元组改为：
```python
    rules = (_rule_function_length, _rule_too_many_params, _rule_single_letter_param,
             _rule_deep_nesting, _rule_boolean_state_flags)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: 11 passed

---

### Task 3: rules.py 字面量规则（104 magic_number / 105 bare_string_enum）

**Files:**
- Modify: `skills/argus-code-maintainability-scan/implementation/rules.py`
- Modify: `tests/unit/test_code_maintainability.py`

- [ ] **Step 1: 写失败测试**（追加）
```python
def test_104_magic_number_detected():
    assert any(h.rule_id == "CODE-104"
               for h in _hits("def calc(price):\n    return price * 0.8\n"))


def test_104_whitelisted_number_ok():
    assert not any(h.rule_id == "CODE-104"
                   for h in _hits("def calc(price):\n    return price + 1\n"))


def test_104_name_times_name_ok():
    assert not any(h.rule_id == "CODE-104"
                   for h in _hits("def calc(a, b):\n    return a * b\n"))


def test_105_bare_string_enum_detected():
    text = ("def label(status):\n"
            '    if status == "pending":\n        return True\n'
            '    if status == "paid":\n        return True\n'
            '    if status == "shipped":\n        return True\n'
            "    return False\n")
    assert any(h.rule_id == "CODE-105" for h in _hits(text))


def test_105_less_than_three_values_ok():
    text = ("def label(status):\n"
            '    if status == "pending":\n        return True\n'
            '    if status == "paid":\n        return True\n'
            "    return False\n")
    assert not any(h.rule_id == "CODE-105" for h in _hits(text))
```

- [ ] **Step 2: 运行确认失败**

Expected: 新增 5 条 FAIL

- [ ] **Step 3: 实现**（加正则与两个规则函数，注册进 `scan_path`）
```python
_MAGIC_NUM_RE = re.compile(
    r"\b[A-Za-z_]\w*\s*([*+\-/])\s*(\d+(?:\.\d+)?)\b"
    r"|\b(\d+(?:\.\d+)?)\s*([*+\-/])\s*[A-Za-z_]\w*\b"
)
_ENUM_STR_RE = re.compile(r"(?:==|!=|in)\s*['\"]([a-z][a-z0-9_]*)['\"]")


def _rule_magic_number(lines):
    for i, line in enumerate(lines):
        # 注释里的字形（如 `# CODE-104:`）不是算术运算中的魔法数字，跳过整行注释。
        if line.strip().startswith("#"):
            continue
        for m in _MAGIC_NUM_RE.finditer(line):
            num = m.group(2) if m.group(2) is not None else m.group(3)
            try:
                val = float(num)
            except ValueError:
                continue
            if val in _MAGIC_WHITELIST:
                continue
            return [_hit(
                "CODE-104", "code.magic_number", "low", 0.75, i + 1, i + 1,
                f"Magic number '{num}' used in arithmetic with a named operand",
                "Numeric literal appears where a named constant expresses intent",
                "有业务含义的数值提为命名常量，如 VIP_DISCOUNT_RATE = 0.8", line)]
    return []


def _rule_bare_string_enum(lines):
    seen = set()
    for i, line in enumerate(lines):
        for m in _ENUM_STR_RE.finditer(line):
            seen.add(m.group(1))
            if len(seen) >= 3:
                return [_hit(
                    "CODE-105", "code.bare_string_enum", "medium", 0.8, i + 1, i + 1,
                    "Bare string literals used as status/enum values",
                    f"enum-like values: {sorted(seen)}",
                    "有限状态用枚举/明确类型表达，不散落字符串字面量", line)]
    return []
```
`scan_path` 的 `rules` 追加 `_rule_magic_number, _rule_bare_string_enum`。

- [ ] **Step 4: 运行确认通过**

Expected: 16 passed

---

### Task 4: rules.py 链式规则（107 mapping_if_chain / 108 or_chain_membership）

**Files:**
- Modify: `skills/argus-code-maintainability-scan/implementation/rules.py`
- Modify: `tests/unit/test_code_maintainability.py`

- [ ] **Step 1: 写失败测试**（追加）
```python
def test_107_mapping_if_chain_detected():
    text = ("def discount(t):\n"
            '    if t == "normal":\n        return 1.0\n'
            '    elif t == "vip":\n        return 0.8\n'
            '    elif t == "svip":\n        return 0.7\n'
            '    elif t == "employee":\n        return 0.5\n'
            "    return 1.0\n")
    assert any(h.rule_id == "CODE-107" for h in _hits(text))


def test_107_three_branch_ok():
    text = ("def discount(t):\n"
            '    if t == "normal":\n        return 1.0\n'
            '    elif t == "vip":\n        return 0.8\n'
            '    elif t == "svip":\n        return 0.7\n'
            "    return 1.0\n")
    assert not any(h.rule_id == "CODE-107" for h in _hits(text))


def test_108_or_chain_detected():
    text = ('def has(role):\n'
            '    if role == "admin" or role == "owner" or role == "superuser":\n'
            "        return True\n"
            "    return False\n")
    assert any(h.rule_id == "CODE-108" for h in _hits(text))


def test_108_two_branch_ok():
    text = ('def has(role):\n'
            '    if role == "admin" or role == "owner":\n'
            "        return True\n"
            "    return False\n")
    assert not any(h.rule_id == "CODE-108" for h in _hits(text))
```

- [ ] **Step 2: 运行确认失败**

Expected: 新增 4 条 FAIL

- [ ] **Step 3: 实现**（加正则与两个规则函数，注册进 `scan_path`）
```python
_ELIF_RE = re.compile(r"^\s*elif\b")
_SINGLE_RETURN_LITERAL_RE = re.compile(r"^\s*return\s+(['\"]|\d)")
_OR_CHAIN_RE = re.compile(
    r"\b(\w+)\s*==\s*['\"][^'\"]+['\"]"
    r"(\s+or\s+\1\s*==\s*['\"][^'\"]+['\"]){2,}"
)


def _rule_mapping_if_chain(lines):
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*if\b", lines[i]):
            i += 1
            continue
        indent = len(_INDENT.match(lines[i]).group(1))
        branches = []
        j = i
        while j < len(lines):
            if (re.match(r"^\s*(if|elif)\b", lines[j])
                    and len(_INDENT.match(lines[j]).group(1)) == indent):
                body = lines[j + 1] if j + 1 < len(lines) else ""
                if not _SINGLE_RETURN_LITERAL_RE.match(body):
                    break
                branches.append(j)
                j += 2
            else:
                break
        if len(branches) >= 4:
            return [_hit(
                "CODE-107", "code.mapping_if_chain", "medium", 0.85, i + 1, i + 1,
                f"If/elif chain of {len(branches)} branches maps inputs to constants",
                "Pure mapping expressed as control flow",
                "纯映射关系优先用映射表/字典，而不是 if/elif", lines[i])]
        i = j if j > i else i + 1
    return []


def _rule_or_chain_membership(lines):
    for i, line in enumerate(lines):
        if _OR_CHAIN_RE.search(line):
            return [_hit(
                "CODE-108", "code.or_chain_membership", "medium", 0.85, i + 1, i + 1,
                "3+ 'var == literal' branches joined by 'or' should be a membership check",
                "Repeated equality on the same variable",
                "用集合表达成员关系：if role in PRIVILEGED_ROLES", line)]
    return []
```
`scan_path` 的 `rules` 追加 `_rule_mapping_if_chain, _rule_or_chain_membership`。

- [ ] **Step 4: 运行确认通过**

Expected: 20 passed

---

### Task 5: rules.py 数据结构规则（109 parallel_arrays / 110 linear_scan_no_index）

**Files:**
- Modify: `skills/argus-code-maintainability-scan/implementation/rules.py`
- Modify: `tests/unit/test_code_maintainability.py`

- [ ] **Step 1: 写失败测试**（追加）
```python
def test_109_parallel_arrays_detected():
    text = ("names = ['a', 'b']\n"
            "ages = [1, 2]\n"
            "emails = ['x', 'y']\n"
            "for i in range(len(names)):\n"
            "    print(names[i], ages[i], emails[i])\n")
    assert any(h.rule_id == "CODE-109" for h in _hits(text))


def test_109_single_list_ok():
    text = ("names = ['a', 'b']\n"
            "for i in range(len(names)):\n"
            "    print(names[i])\n")
    assert not any(h.rule_id == "CODE-109" for h in _hits(text))


def test_110_linear_scan_detected():
    text = ("users = [{'id': 1}, {'id': 2}]\n"
            "orders = [{'uid': 1}]\n"
            "for o in orders:\n"
            "    for u in users:\n"
            "        if o.uid == u.id:\n"
            "            print(o)\n")
    assert any(h.rule_id == "CODE-110" for h in _hits(text))


def test_110_no_nested_join_ok():
    text = ("users = []\n"
            "for u in users:\n"
            "    print(u)\n")
    assert not any(h.rule_id == "CODE-110" for h in _hits(text))
```

- [ ] **Step 2: 运行确认失败**

Expected: 新增 4 条 FAIL

- [ ] **Step 3: 实现**（加正则与两个规则函数，注册进 `scan_path`）
```python
_LIST_ASSIGN_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*\[")


def _rule_parallel_arrays(lines):
    lists = {m.group(1) for m in (_LIST_ASSIGN_RE.match(l) for l in lines) if m}
    if len(lists) < 2:
        return []
    for i, line in enumerate(lines):
        m = re.search(r"for\s+(\w+)\s+in\s+range\(len\((\w+)\)\):", line)
        if not m:
            continue
        idx = m.group(1)
        indexed = set()
        j = i + 1
        while j < len(lines) and len(_INDENT.match(lines[j]).group(1)) > 0:
            for name in lists:
                if re.search(rf"\b{re.escape(name)}\s*\[{re.escape(idx)}\]", lines[j]):
                    indexed.add(name)
            j += 1
        if len(indexed) >= 2:
            return [_hit(
                "CODE-109", "code.parallel_arrays", "low", 0.6, i + 1, i + 1,
                f"Parallel lists indexed by the same index '{idx}': {sorted(indexed)}",
                "Ordering between parallel lists is preserved only by convention",
                "用业务对象(数据类)或按主键索引替代平行数组", line)]
    return []


def _rule_linear_scan_no_index(lines):
    for i, line in enumerate(lines):
        outer = re.match(r"^for\s+(\w+)\s+in\s+(\w+):", line)
        if not outer or _INDENT.match(line).group(1) != "":
            continue
        o_var = outer.group(1)
        j = i + 1
        while j < len(lines):
            inner = re.match(r"^\s*for\s+(\w+)\s+in\s+(\w+):", lines[j])
            if inner and inner.group(2) != o_var and inner.group(2) != outer.group(2):
                i_var = inner.group(1)
                k = j + 1
                while k < len(lines) and len(_INDENT.match(lines[k]).group(1)) > 0:
                    if re.search(rf"\b{o_var}\.\w+\s*==\s*{i_var}\.\w+"
                                 rf"|\b{i_var}\.\w+\s*==\s*{o_var}\.\w+", lines[k]):
                        return [_hit(
                            "CODE-110", "code.linear_scan_no_index", "medium", 0.7, i + 1, i + 1,
                            f"Nested loop joins '{o_var}' to '{i_var}' by equality without an index",
                            "Inner collection scanned linearly for every outer element",
                            "按主访问模式建立索引：{b}_by_key = {{x.key: x for x in b}}", lines[i])]
                    k += 1
                break
            j += 1
    return []
```
`scan_path` 的 `rules` 追加 `_rule_parallel_arrays, _rule_linear_scan_no_index`（此时 11 条全注册）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: 24 passed

---

### Task 6: skill adapter（main.py + 三个 schema）

**Files:**
- Create: `skills/argus-code-maintainability-scan/implementation/main.py`
- Create: `skills/argus-code-maintainability-scan/schemas/input.schema.json`
- Create: `skills/argus-code-maintainability-scan/schemas/output.schema.json`
- Create: `skills/argus-code-maintainability-scan/schemas/error.schema.json`
- Create: `tests/unit/test_maintainability_skill.py`

**Interfaces:**
- Consumes: Task 1-5 的 `scan_path`/`RuleHit`；`skills/_shared/llm_review.py`（存在则用）
- Produces: `invoke(payload: dict) -> dict`、`main(argv) -> int`（`--input`/`--output`，失败 exit 2）

- [ ] **Step 1: 写失败测试**

`tests/unit/test_maintainability_skill.py`：
```python
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "argus-code-maintainability-scan" / "implementation"))
from main import invoke, main  # noqa: E402


def _payload(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append({"path": rel, "sha256": "0" * 64, "size": len(content)})
    return {"schema_version": "1", "run_id": "r", "snapshot_id": "s",
            "source_root": str(tmp_path), "files": snaps}


def test_invoke_detects_magic_number(tmp_path):
    payload = _payload(tmp_path, {"app/pricing.py": "def calc(price):\n    return price * 0.8\n"})
    result = invoke(payload)
    assert result["status"] == "completed"
    assert any(f["category"] == "code.magic_number" for f in result["findings"])


def test_invoke_ignores_non_python(tmp_path):
    payload = _payload(tmp_path, {"app/app.js": "const x = 0.8;\n"})
    assert invoke(payload)["findings"] == []


def test_invoke_finding_has_p4_shape(tmp_path):
    payload = _payload(tmp_path, {"app/pricing.py": "def calc(price):\n    return price * 0.8\n"})
    f = invoke(payload)["findings"][0]
    assert f["agent"] == "code"
    assert f["evidence"]["source_sha256"] == "0" * 64
    assert f["fingerprint"].startswith(("0", "1", "2", "3", "4", "5", "6", "7",
                                        "8", "9", "a", "b", "c", "d", "e", "f"))


def test_main_writes_output(tmp_path):
    payload = _payload(tmp_path, {"a.py": "def f(x):\n    return x\n"})
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    rc = main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["status"] == "completed"


def test_main_invalid_input_exit2(tmp_path):
    in_path = tmp_path / "bad.json"
    out_path = tmp_path / "out.json"
    in_path.write_text("not json", encoding="utf-8")
    rc = main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 2
    assert json.loads(out_path.read_text(encoding="utf-8"))["status"] == "failed"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_maintainability_skill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: 写实现**

`skills/argus-code-maintainability-scan/implementation/main.py`：
```python
#!/usr/bin/env python3
"""argus-code-maintainability-scan: standalone maintainability auditor.

No host imports. Scans the immutable snapshot's Python files with the shared
rules module and emits schema-valid findings. Detects: long functions, too
many params, deep nesting, magic numbers, bare-string enums, boolean state
flags, mapping if-chains, or-chains, parallel arrays, linear scans, and
single-letter params.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

_skill_dir = Path(__file__).resolve().parent
_shared_dir = _skill_dir.parent.parent / "_shared"
if _shared_dir.is_dir():
    sys.path.insert(0, str(_shared_dir))
try:
    from llm_review import review_finding  # type: ignore
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

sys.path.insert(0, str(_skill_dir))
from rules import RuleHit, scan_path  # noqa: E402

_FINGERPRINT_SALT = b"argus-code-maintainability-salt"


def _fingerprint(raw: str) -> str:
    return hmac.new(_FINGERPRINT_SALT, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _llm_review_findings(findings: list, source_root: Path) -> list:
    if not (_LLM_AVAILABLE and findings):
        return findings
    reviewed = []
    for f in findings:
        ctx = ""
        fp = source_root / f.get("file", "")
        if fp.exists():
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            lo = max(0, f.get("line_start", 1) - 5)
            hi = min(len(lines), f.get("line_end", f.get("line_start", 1)) + 5)
            ctx = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines[lo:hi], start=lo))
        review = review_finding(f, ctx)
        f["llm_review"] = review
        if review["verdict"] == "NO":
            f["confidence"] = max(0.1, f["confidence"] * 0.3)
            f["llm_suppressed"] = True
        elif review["verdict"] == "YES":
            f["confidence"] = min(1.0, f["confidence"] * 1.2)
        reviewed.append(f)
    return reviewed


def invoke(payload: dict) -> dict:
    source_root = Path(payload["source_root"])
    findings = []
    for sf in payload.get("files", []):
        if not sf["path"].endswith(".py"):
            continue
        text = (source_root / sf["path"]).read_text(encoding="utf-8", errors="replace")
        for hit in scan_path(sf["path"], text):
            findings.append({
                "id": f"{hit.category}-{sf['path']}:{hit.line_start}",
                "agent": "code", "category": hit.category,
                "severity": hit.severity, "confidence": hit.confidence,
                "title": hit.title, "detail": hit.detail,
                "file": sf["path"], "line_start": hit.line_start,
                "line_end": hit.line_end,
                "remediation": hit.remediation,
                "verification": "rerun Code Auditor on the new snapshot",
                "rollback": None, "cwe": None,
                "fingerprint": _fingerprint(f"{hit.category}:{sf['path']}:{hit.line_start}"),
                "rule_id": hit.rule_id, "rule_version": "1",
                "evidence": {"detector": f"code.{hit.category.split('.')[-1]}-detect",
                             "source_sha256": sf["sha256"], "redacted": False},
            })
    return {"schema_version": "1", "status": "completed", "agent": "code",
            "input_snapshot_id": payload.get("snapshot_id", ""),
            "findings": _llm_review_findings(findings, source_root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = invoke(payload)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
        error = {"schema_version": "1", "status": "failed",
                 "error_code": "INVALID_INPUT", "error_message": str(exc)[:500]}
        Path(args.output).write_text(
            json.dumps(error, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

三个 schema 文件（`additionalProperties: false` 是 contract 测试硬性要求）——镜像 `argus-code-rule-scan` 的 schema，`input.schema.json` 顶层加 `additionalProperties: false`：

`schemas/input.schema.json`：
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "run_id", "snapshot_id", "source_root", "files"],
  "properties": {
    "schema_version": {"const": "1"},
    "run_id": {"type": "string"},
    "snapshot_id": {"type": "string"},
    "source_root": {"type": "string"},
    "profile": {"type": "string"},
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["path", "sha256", "size"],
        "properties": {
          "path": {"type": "string"},
          "sha256": {"type": "string"},
          "size": {"type": "integer"},
          "language": {"type": ["string", "null"]}
        }
      }
    }
  }
}
```

`schemas/output.schema.json`：
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "status", "agent", "input_snapshot_id", "findings"],
  "properties": {
    "schema_version": {"const": "1"},
    "status": {"const": "completed"},
    "agent": {"type": "string"},
    "input_snapshot_id": {"type": "string"},
    "findings": {"type": "array", "items": {"type": "object"}}
  }
}
```

`schemas/error.schema.json`：
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "status", "error_code", "error_message"],
  "properties": {
    "schema_version": {"const": "1"},
    "status": {"const": "failed"},
    "error_code": {"type": "string"},
    "error_message": {"type": "string"}
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_maintainability_skill.py tests/contract/test_skill_contracts.py -v`
Expected: skill 5 passed；contract 测试通过（新 skill 满足布局/schema/禁止条款检查）

---

### Task 7: SKILL.md + manifest.yaml

**Files:**
- Create: `skills/argus-code-maintainability-scan/SKILL.md`
- Create: `skills/argus-code-maintainability-scan/manifest.yaml`

- [ ] **Step 1: 写文件**

`SKILL.md`：
```markdown
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
```

`manifest.yaml`：
```yaml
name: argus-code-maintainability-scan
version: 0.1.0
owner: argus
license: Apache-2.0
category: assessor
purpose: Deterministic headless assessor Skill that scans the immutable source snapshot for maintainability smells.
execution:
  command: ["python3", "implementation/main.py"]
  input: json-file
  output: json-file
  timeoutSeconds: 60
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
error_schema: schemas/error.schema.json
permissions:
  - snapshot.read
  - own_task_artifact.write
network: true  # AI Gateway access for LLM deep review
idempotency: input_digest
reusable_by: [argus]
```

- [ ] **Step 2: 运行 contract 测试确认通过**

Run: `python -m pytest tests/contract/test_skill_contracts.py -v`
Expected: 全过（SKILL.md 含「禁止」、manifest/schemas/main.py 齐全）

---

### Task 8: host 适配 + 接入 CodeDetector + identity.yaml

**Files:**
- Create: `agents/code/maintainability.py`
- Modify: `agents/code/detector.py`
- Modify: `agents/code/identity.yaml`
- Modify: `tests/unit/test_code_maintainability.py`（追加 detector 级测试）

**Interfaces:**
- Consumes: Task 1-5 的 `rules.scan_path`/`RuleHit`；`core.schemas.Finding/Evidence/SourceSnapshot/SnapshotFile`；`core.redaction.hmac_fingerprint`
- Produces: `scan_snapshot(snapshot: SourceSnapshot) -> tuple[Finding, ...]`（host 侧，供 detector 调用）

- [ ] **Step 1: 写失败测试**（追加到 `test_code_maintainability.py` 顶部 import + 末尾用例）
```python
# 文件顶部追加 import
from core.schemas import SnapshotFile, SourceSnapshot
from agents.code.detector import CodeDetector


def _snap(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append(SnapshotFile(path=rel, sha256="0" * 64, size=len(content)))
    return SourceSnapshot(root=str(tmp_path), files=tuple(snaps))


# 文件末尾追加用例
def test_detector_emits_maintainability_finding(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def calc(price):\n    return price * 0.8\n"})
    assert any(f.category == "code.magic_number"
               for f in CodeDetector().detect(snap))


def test_detector_clean_code_no_maintainability(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def apply(amount, rate):\n    return amount * rate\n"})
    assert not any(f.category.startswith("code.") and f.category != "code.placeholder"
                   for f in CodeDetector().detect(snap))


def test_detector_finding_carries_p4_evidence(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def calc(price):\n    return price * 0.8\n"})
    f = next(f for f in CodeDetector().detect(snap)
             if f.category == "code.magic_number")
    assert f.evidence.source_sha256 == "0" * 64
    assert f.agent == "code"
    assert f.rule_id == "CODE-104"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_code_maintainability.py -k detector -v`
Expected: FAIL — `AttributeError: module 'rules' has no attribute ...` 或 import 错误（host 适配未接）

- [ ] **Step 3: 写实现**

`agents/code/maintainability.py`：
```python
"""Host-side adapter: shared maintainability rules -> schema Finding.

Rules live in the standalone skill module; this bridge converts RuleHit to
Finding so the deterministic local engine reports the same findings as the
AgentTeams skill. Uses sys.path so the host can import the pure-stdlib rules
module without coupling packages (the skill stays standalone).
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.redaction import hmac_fingerprint
from core.schemas import Evidence, Finding, SourceSnapshot

_SALT = b"argus-code-maintainability-salt"
_rules_dir = (Path(__file__).resolve().parents[2]
              / "skills" / "argus-code-maintainability-scan" / "implementation")
if str(_rules_dir) not in sys.path:
    sys.path.insert(0, str(_rules_dir))
from rules import RuleHit, scan_path  # noqa: E402


def scan_snapshot(snapshot: SourceSnapshot) -> tuple[Finding, ...]:
    out: list[Finding] = []
    for sf in snapshot.files:
        if not sf.path.endswith(".py"):
            continue
        text = (Path(snapshot.root) / sf.path).read_text(encoding="utf-8",
                                                         errors="replace")
        for hit in scan_path(sf.path, text):
            out.append(_to_finding(sf, hit))
    return tuple(out)


def _to_finding(sf, hit: RuleHit) -> Finding:
    return Finding(
        id=f"{hit.category}-{sf.path}:{hit.line_start}",
        agent="code",
        category=hit.category,
        severity=hit.severity,
        confidence=hit.confidence,
        title=hit.title,
        detail=hit.detail,
        remediation=hit.remediation,
        verification="rerun Code Auditor on the new snapshot",
        fingerprint=hmac_fingerprint(
            f"{hit.category}:{sf.path}:{hit.line_start}", _SALT),
        rule_id=hit.rule_id,
        rule_version="1",
        file=sf.path,
        line_start=hit.line_start,
        line_end=hit.line_end,
        rollback=None,
        cwe=None,
        evidence=Evidence(
            context_lines=(hit.excerpt,),
            source_sha256=sf.sha256,
            redacted_value=None,
            detector=f"code.{hit.category.split('.')[-1]}-detect",
            reasoning_summary=None,
        ),
    )
```

修改 `agents/code/detector.py`：把现有 `detect` 逻辑改为保留占位符检测 + 追加维护性：
```python
"""Code Auditor：占位实现检测 + 可维护性审查（初赛最小规则集）。"""
from __future__ import annotations

import re
from pathlib import Path

from core.redaction import hmac_fingerprint, redact
from core.schemas import Evidence, Finding, SourceSnapshot
from agents.code.maintainability import scan_snapshot

# ...（保留原有 _FINGERPRINT_SALT/_SOURCE_EXTS/PLACEHOLDER 不变）...

class CodeDetector:
    def detect(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        out = list(self._placeholder_findings(snapshot))
        out.extend(scan_snapshot(snapshot))
        return tuple(out)

    def _placeholder_findings(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        # 原 detect() 的占位符逻辑原样搬到这里
        out: list[Finding] = []
        for sf in snapshot.files:
            if not sf.path.endswith(_SOURCE_EXTS):
                continue
            text = self._read(snapshot.root, sf.path)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if not PLACEHOLDER.search(line):
                    continue
                excerpt = redact(line.strip()[:300])
                out.append(Finding(
                    id=f"code-placeholder-{sf.path}:{line_no}",
                    agent="code", category="code.placeholder",
                    severity="medium", confidence=0.82,
                    title="Placeholder implementation remains in production code",
                    detail="A placeholder marker indicates incomplete behavior",
                    file=sf.path, line_start=line_no, line_end=line_no,
                    remediation="replace the placeholder with a complete implementation",
                    verification="rerun Code Auditor on the new snapshot",
                    rollback=None, cwe=None,
                    fingerprint=hmac_fingerprint(
                        f"code.placeholder:{sf.path}:{line_no}", _FINGERPRINT_SALT),
                    rule_id="CODE-001", rule_version="1",
                    evidence=Evidence(
                        context_lines=(excerpt,),
                        source_sha256=sf.sha256,
                        redacted_value=None,
                        detector="code.placeholder-detect",
                        reasoning_summary=None,
                    ),
                ))
        return tuple(out)

    def _read(self, root: str, path: str) -> str:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")
```

修改 `agents/code/identity.yaml`：
```yaml
capabilities:
  - code_rule_scan
  - placeholder_detect
  - state_machine_check
  - maintainability_scan
optional_skills:
  - argus-code-maintainability-scan
  - semgrep
  - github_readonly
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_code_maintainability.py -v`
Expected: 27 passed（24 规则级 + 3 detector 级）

- [ ] **Step 5: 回归确认**

Run: `python -m pytest tests/unit/test_code_detector.py tests/unit/test_meta.py tests/unit/test_policy.py -v`
Expected: 全过（占位符检测行为不变）

---

### Task 9: parity 测试（skill vs host detector 同语料一致）

**Files:**
- Modify: `tests/unit/test_maintainability_skill.py`（追加 parity 用例）

- [ ] **Step 1: 写失败测试**（追加到 `test_maintainability_skill.py`）
```python
from agents.code.detector import CodeDetector
from core.schemas import SnapshotFile, SourceSnapshot

_SMELLY = (
    "def order_is_active(status):\n"
    '    if status == "pending":\n        return True\n'
    '    if status == "paid":\n        return True\n'
    '    if status == "shipped":\n        return True\n'
    "    return False\n"
    "\n"
    "def calc(price):\n"
    "    return price * 0.8\n"
)


def _detector_keys(tmp_path, text):
    snap = SourceSnapshot(
        root=str(tmp_path),
        files=(SnapshotFile(path="app/pricing.py", sha256="0" * 64, size=len(text)),),
    )
    return {(f.agent, f.category, f.file, f.line_start)
            for f in CodeDetector().detect(snap)
            if f.category != "code.placeholder"}


def test_parity_skill_vs_host_detector(tmp_path):
    p = tmp_path / "app"
    p.mkdir(parents=True)
    (p / "pricing.py").write_text(_SMELLY, encoding="utf-8")
    payload = _payload(tmp_path, {"app/pricing.py": _SMELLY})
    skill_keys = {(f["agent"], f["category"], f["file"], f["line_start"])
                  for f in invoke(payload)["findings"]}
    assert skill_keys == _detector_keys(tmp_path, _SMELLY)
    assert skill_keys  # non-empty: the corpus triggers rules on both sides
```

- [ ] **Step 2: 运行确认通过**

Run: `python -m pytest tests/unit/test_maintainability_skill.py::test_parity_skill_vs_host_detector -v`
Expected: PASS（两侧共用同一 rules.py，adapter 不丢数据）

---

### Task 10: 评测场景 simple-maintainability

**Files:**
- Create: `demo/eval/simple/simple-maintainability/src/app/pricing.py`
- Create: `demo/eval/simple/simple-maintainability/ground-truth.json`
- Modify: `demo/eval/manifest.json`
- Modify: `demo/eval/README.md`

**Interfaces:**
- Consumes: Task 8 的 detector 行为（精确 5 条 finding，见 fixture 工程约束）

- [ ] **Step 1: 生成 fixture（确定行号）**

运行下面脚本生成 `src/app/pricing.py`（105 行函数体保证 CODE-101 触发；行号由本脚本固定）：
```bash
python - <<'PY'
import pathlib
root = pathlib.Path("demo/eval/simple/simple-maintainability/src/app")
root.mkdir(parents=True, exist_ok=True)
head = '''"""Pricing module.

Deliberately smelly fixture for the Argus maintainability eval scenario.
Each smell maps to one CODE-1xx rule; the file must NOT trigger any other rule.
"""
from __future__ import annotations


def order_is_active(status):
    # CODE-105: bare-string status comparisons
    if status == "pending":
        return True
    if status == "processing":
        return True
    if status == "paid":
        return True
    return status != "cancelled"


def discount_for(user_type):
    # CODE-107: mapping if/elif chain
    if user_type == "normal":
        return 1.0
    elif user_type == "vip":
        return 0.8
    elif user_type == "svip":
        return 0.7
    elif user_type == "employee":
        return 0.5
    return 1.0


def has_admin_role(role):
    # CODE-108: or-chain membership
    if role == "admin" or role == "owner" or role == "superuser":
        return True
    return False


def apply_vip_discount(amount, is_vip):
    # CODE-104: magic number
    if is_vip:
        return amount * 0.8
    return amount


def calculate_bulk_quote(unit_price, quantity, region, is_prime):
    # CODE-101: function body > 100 non-blank lines
    total = unit_price * quantity
'''
body = "".join("    total = total + 1\n" for _ in range(104))
tail = "    return total\n"
(root / "pricing.py").write_text(head + body + tail, encoding="utf-8")
print("lines:", (head + body + tail).count("\n") + 1)
PY
```
Expected 输出 `lines: 154`。**固定行号断言**（fixture 工程约束：只触发 5 条，见 spec §9）：
- CODE-101 → line 47（`def calculate_bulk_quote`)
- CODE-104 → line 43（`return amount * 0.8`）
- CODE-105 → line 15（第 3 个枚举值 `"paid"` 出现处）
- CODE-107 → line 22（`if user_type == "normal":`）
- CODE-108 → line 35（or-chain）
- **不触发** 102/103/106/109/110/111（参数 ≤4、嵌套 ≤1、无布尔标志赋值、无模块级列表、无嵌套 join、无单字母参数）

- [ ] **Step 2: 写 ground-truth**

`demo/eval/simple/simple-maintainability/ground-truth.json`：
```json
{
  "schema_version": "1",
  "scenario_id": "simple-maintainability",
  "category": "simple",
  "title": "Code maintainability smells",
  "description": "pricing.py 植入 5 个确定性可维护性信号（长函数/魔法数字/裸字符串枚举/映射链/or链）。code agent 应精确产出这 5 条 finding，gate=warn。",
  "expected_gate": "warn",
  "expected_findings": [
    {"key": "mt-function-length", "agent": "code", "category": "code.function_length",
     "severity": "low", "file": "app/pricing.py", "line_start": 47, "line_end": 47,
     "title": "Function body exceeds 100 non-blank lines"},
    {"key": "mt-magic-number", "agent": "code", "category": "code.magic_number",
     "severity": "low", "file": "app/pricing.py", "line_start": 43, "line_end": 43,
     "title": "Magic number used in arithmetic with a named operand"},
    {"key": "mt-bare-enum", "agent": "code", "category": "code.bare_string_enum",
     "severity": "medium", "file": "app/pricing.py", "line_start": 15, "line_end": 15,
     "title": "Bare string literals used as status/enum values"},
    {"key": "mt-map-chain", "agent": "code", "category": "code.mapping_if_chain",
     "severity": "medium", "file": "app/pricing.py", "line_start": 22, "line_end": 22,
     "title": "If/elif chain maps inputs to constants"},
    {"key": "mt-or-chain", "agent": "code", "category": "code.or_chain_membership",
     "severity": "medium", "file": "app/pricing.py", "line_start": 35, "line_end": 35,
     "title": "3+ 'var == literal' branches joined by 'or' should be a membership check"}
  ],
  "annotation": {
    "annotator": "human-review",
    "independent_of": "meta-detector",
    "notes": "低置信启发式(103/106/109/110/111)不在本场景——fixture 工程上避免触发，只测高置信 5 条。"
  }
}
```

- [ ] **Step 3: 登记 manifest**

`demo/eval/manifest.json` 的 `scenarios` 数组追加：
```json
{"id": "simple-maintainability", "category": "simple", "path": "simple/simple-maintainability"}
```

- [ ] **Step 4: 写场景级校验测试**（追加到 `tests/unit/test_eval_harness.py` 或独立 `tests/unit/test_eval_maintainability.py`）
```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GT = (ROOT / "demo/eval/simple/simple-maintainability/ground-truth.json")
SRC = (ROOT / "demo/eval/simple/simple-maintainability/src/app/pricing.py")


def test_ground_truth_line_numbers_match_fixture():
    gt = json.loads(GT.read_text(encoding="utf-8"))
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()
    for exp in gt["expected_findings"]:
        lo = exp["line_start"] - 1
        assert 0 <= lo < len(lines), exp["key"]
        # 每个 ground-truth finding 的行必须有可辨别的信号
        assert lines[lo].strip(), exp["key"]


def test_fixture_does_not_trigger_heuristic_rules():
    import sys
    sys.path.insert(0, str(ROOT / "skills/argus-code-maintainability-scan/implementation"))
    from rules import scan_path
    text = SRC.read_text(encoding="utf-8")
    rules = {h.rule_id for h in scan_path("app/pricing.py", text)}
    assert {"CODE-101", "CODE-104", "CODE-105", "CODE-107", "CODE-108"} <= rules
    assert not rules & {"CODE-102", "CODE-103", "CODE-106", "CODE-109", "CODE-110", "CODE-111"}
```

- [ ] **Step 5: 运行新场景 + 回归**

Run: `python -m pytest tests/unit/test_eval_maintainability.py -v`
Expected: PASS（行号断言 + 只触发 5 条断言）

Run: `python demo/eval/harness.py --engine local --runs 1 --only simple-maintainability`
Expected: `simple-maintainability` MATCH；`gate` 为 warn（meta 对 3 条 medium finding 标 VERIFIED）

Run: `python demo/eval/harness.py --engine local --runs 1`
Expected: 既有 8 场景不回归（尤其 `simple-clean` 零误报）；无审计错误

---

### Task 11: skill 登记 + 全量回归 + gate 重 pin

**Files:**
- Modify: `skills/skills.lock.json`
- Modify: `demo/eval/README.md`（场景表加行，可选）

- [ ] **Step 1: 计算新 skill digest 并登记 lock**

先确认 `skills/argus-code-maintainability-scan/` 全部文件就位（Task 1-9 产物），再运行：
```bash
python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "agentteams")
from hiclaw_client import skill_directory_digest

lock_path = Path("skills/skills.lock.json")
lock = json.loads(lock_path.read_text(encoding="utf-8"))
name = "argus-code-maintainability-scan"
digest = skill_directory_digest(Path("skills") / name)
entry = {"name": name, "version": "0.0.1", "local_sha256": digest}
lock["skills"] = [s for s in lock["skills"] if s["name"] != name] + [entry]
assign = lock["assignments"].setdefault("argus-code", [])
for s in ("argus-finding-emit", "argus-code-rule-scan"):
    if s not in assign:
        assign.append(s)
if name not in assign:
    assign.append(name)
lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
print("registered", name, digest[:16])
PY
```
Expected: 打印 `registered argus-code-maintainability-scan <sha256前16位>`

- [ ] **Step 2: 全量单测 + contract + eval 回归**

Run: `python -m pytest tests/unit tests/contract -q`
Expected: 全绿（283 + 新增 24 规则 + 5 skill + 3 detector + 2 parity + 2 eval 场景级）
Run: `python demo/eval/harness.py --engine local --runs 1`
Expected: 9 场景无审计错误；既有 8 场景不回归

- [ ] **Step 3: gate 重 pin（eval 指纹已变）**

Run: `python demo/eval/gate.py --pin --force`
Expected: exit 0，`eval.lock.json` 更新 baseline（含新场景 `simple-maintainability`）

- [ ] **Step 4: P4 抽查**

Run: `python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "demo/eval")
# 重跑一次 maintenability 场景的 audit 报告，检查 findings 无源码正文
PY`
并人工抽查：`simple-maintainability` 的 audit 报告里所有 `code.*` finding 的 evidence/context 只有脱敏摘录与 hmac，无 `def calculate_bulk_quote` 之类的函数体源码片段。

- [ ] **Step 5: 验收清单对账**

对照 spec §12 逐条打勾：规则单测 / parity / harness MATCH / simple-clean 不回归 / 全量 pytest / gate 重 pin / P4 抽查。AgentTeams worker 侧同步（`apply_worker_config` 或 `publish_nacos`）依赖 docker 可用时再执行——**不在本计划必做范围**（本地引擎评测不需要）。

---

## Self-Review

**Spec coverage：**
- §4 11 条规则 → Task 1-5（每条 TDD）
- §3.1 规则模块 + parity → Task 1（rules.py）+ Task 9（parity 测试）
- §3.1 skill adapter + schema → Task 6
- §3.1 SKILL.md + manifest → Task 7
- §3.2 host 适配 + CodeDetector 接入 → Task 8
- §3.3 语言范围（v1 仅 Python）→ rules.py `scan_path` 非 .py 直接空
- §5 P4 → rules.py `_redact` + host/skill 均只存 excerpt + fingerprint
- §6 门禁语义（warn 不 block；code 失败 fail-closed；规则防御性）→ 全部规则 low/medium、`scan_path` try/except、Task 8 不改 policy
- §9 评测场景 + fixture 工程约束 + simple-clean 防线 → Task 10
- §11 文件地图 → Task 1-11 全覆盖（identity.yaml / skills.lock.json / manifest / README）
- §12 验收清单 → Task 11 Step 5

**Placeholder scan：** 无 TBD/TODO；所有代码步骤含完整实现；Task 10 用固定行号 + 生成脚本保证确定性。

**Type consistency：** `scan_path(path, text) -> list[RuleHit]` 在 Task 1 定义、Task 6/8 消费，签名一致；`RuleHit` 字段全在 `_hit` 构造。host 与 skill 的 finding id/`evidence.detector` 格式一致（`f"code.{category.split('.')[-1]}-detect"`）。eval ground-truth 行号与 fixture 生成脚本一致（101→47, 104→43, 105→15, 107→22, 108→35）。
