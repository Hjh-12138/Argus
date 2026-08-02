"""Security Auditor 确定性规则。"""
from __future__ import annotations

import re

# 查询文本含 SQL 关键字，并通过字符串拼接/f-string/format 注入变量。
SQL_KEYWORD = re.compile(r"(?i)\b(select|insert|update|delete)\b")
SQL_CONCAT = re.compile(r"(?:\+\s*[A-Za-z_][\w.]*|f['\"].*\{[^}]+\}|\.format\s*\()")

# 捕获完整赋值与 secret value，value 最短 8 字符以减少误报。
HARDCODED_SECRET = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password)\b\s*=\s*['\"]([^'\"]{8,})['\"]"""
)
KNOWN_SECRET_PREFIX = re.compile(r"(?i)^(sk-|AKIA|ghp_|xox[baprs]-)")
