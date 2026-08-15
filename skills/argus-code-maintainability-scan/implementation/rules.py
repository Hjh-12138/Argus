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
_CONTROL_RE = re.compile(r"^(if|elif|for|while|with|try|except|def)\b")
_BOOL_FLAG_RE = re.compile(r"^\s*(is|has|can)_[A-Za-z0-9_]+\s*=\s*(True|False)\b")

_MAGIC_NUM_RE = re.compile(
    r"\b[A-Za-z_]\w*\s*([*+\-/])\s*(\d+(?:\.\d+)?)\b"
    r"|\b(\d+(?:\.\d+)?)\s*([*+\-/])\s*[A-Za-z_]\w*\b"
)
_ENUM_STR_RE = re.compile(r"(?:==|!=|in)\s*['\"]([a-z][a-z0-9_]*)['\"]")

_ELIF_RE = re.compile(r"^\s*elif\b")
_SINGLE_RETURN_LITERAL_RE = re.compile(r"^\s*return\s+(['\"]|\d)")
_OR_CHAIN_RE = re.compile(
    r"\b(\w+)\s*==\s*['\"][^'\"]+['\"]"
    r"(\s+or\s+\1\s*==\s*['\"][^'\"]+['\"]){2,}"
)
_LIST_ASSIGN_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*\[")

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
                            "按主访问模式建立索引：{b}_by_key = {x.key: x for x in b}", lines[i])]
                    k += 1
                break
            j += 1
    return []


def scan_path(path, text):
    if not path.endswith(".py"):
        return []
    lines = text.splitlines()
    rules = (_rule_function_length, _rule_too_many_params, _rule_single_letter_param,
             _rule_deep_nesting, _rule_boolean_state_flags,
             _rule_magic_number, _rule_bare_string_enum,
             _rule_mapping_if_chain, _rule_or_chain_membership,
             _rule_parallel_arrays, _rule_linear_scan_no_index)
    hits = []
    for rule in rules:
        try:
            hits.extend(rule(lines))
        except Exception:
            continue  # a rule bug must not fail the required code auditor
    hits.sort(key=lambda h: (h.line_start, h.rule_id))
    return hits
