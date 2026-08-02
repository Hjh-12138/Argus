"""Security Auditor detector：SQL 注入与硬编码 secret。

禁止原始 secret 出现在 Finding/Evidence/日志；secret fingerprint 使用 HMAC。
"""
from __future__ import annotations

from pathlib import Path

from agents.sec.patterns import HARDCODED_SECRET, KNOWN_SECRET_PREFIX, SQL_CONCAT, SQL_KEYWORD
from core.redaction import hmac_fingerprint, redact
from core.schemas import Evidence, Finding, SourceSnapshot

_FINGERPRINT_SALT = b"argus-sec-finding-salt"
_SECRET_SALT = b"argus-sec-secret-salt"
_SOURCE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".sql")


class SecDetector:
    def detect(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        out: list[Finding] = []
        for sf in snapshot.files:
            if not sf.path.endswith(_SOURCE_EXTS):
                continue
            text = self._read(snapshot.root, sf.path)
            out.extend(self._sql_injection(sf, text))
            out.extend(self._secret(sf, text))
        return tuple(out)

    def _read(self, root: str, path: str) -> str:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")

    def _sql_injection(self, sf, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not (SQL_KEYWORD.search(line) and SQL_CONCAT.search(line)):
                continue
            excerpt = redact(line.strip()[:300])
            findings.append(Finding(
                id=f"sec-sqli-{sf.path}:{line_no}",
                agent="sec",
                category="security.sql_injection",
                severity="critical",
                confidence=0.92,
                title="SQL query concatenates untrusted input",
                detail="SQL statement is built with string interpolation or concatenation",
                file=sf.path,
                line_start=line_no,
                line_end=line_no,
                remediation="use parameterized queries or prepared statements",
                verification="rerun sec detector and inspect query binding",
                rollback=None,
                cwe="CWE-89",
                fingerprint=hmac_fingerprint(
                    f"sec.sqli:{sf.path}:{line_no}", _FINGERPRINT_SALT),
                rule_id="SEC-001",
                rule_version="1",
                evidence=Evidence(
                    context_lines=(excerpt,),
                    source_sha256=sf.sha256,
                    redacted_value=None,
                    detector="sec.dataflow-analyze",
                    reasoning_summary=None,
                ),
            ))
        return findings

    def _secret(self, sf, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            m = HARDCODED_SECRET.search(line)
            if not m:
                continue
            value = m.group(2)
            # 测试/占位值默认不报 critical，避免对 example/placeholder 过度阻断。
            lowered = value.lower()
            if any(x in lowered for x in ("example", "placeholder", "changeme", "your-")):
                continue
            if len(value) < 12 and not KNOWN_SECRET_PREFIX.search(value):
                continue
            excerpt = redact(line.strip()[:300])
            secret_token = hmac_fingerprint(value, _SECRET_SALT)
            findings.append(Finding(
                id=f"sec-secret-{sf.path}:{line_no}",
                agent="sec",
                category="security.secret",
                severity="critical",
                confidence=0.99,
                title="Hardcoded credential detected",
                detail="A credential-like value is hardcoded in source (value redacted)",
                file=sf.path,
                line_start=line_no,
                line_end=line_no,
                remediation="move the value to an environment variable or secret manager",
                verification="scan the new snapshot and review repository history",
                rollback=None,
                cwe="CWE-798",
                fingerprint=hmac_fingerprint(
                    f"sec.secret:{sf.path}:{line_no}:{secret_token}", _FINGERPRINT_SALT),
                rule_id="SEC-002",
                rule_version="1",
                evidence=Evidence(
                    context_lines=(excerpt,),
                    source_sha256=sf.sha256,
                    redacted_value=secret_token,
                    detector="sec.secret-scan",
                    reasoning_summary=None,
                ),
            ))
        return findings
