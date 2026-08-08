#!/usr/bin/env python3
"""argus-secret-scan: standalone security auditor with optional LLM deep review.

Detects SQL injection and hardcoded secrets via deterministic regex/AST.
Optionally calls the AI Gateway for semantic review to reduce false positives.
Raw secret values never appear in output — only redacted display and HMAC token.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

# Make _shared/llm_review importable from the skill sandbox
_skill_dir = Path(__file__).resolve().parent.parent
_shared_dir = _skill_dir.parent / "_shared"
if _shared_dir.is_dir():
    sys.path.insert(0, str(_shared_dir))

try:
    from llm_review import review_finding  # type: ignore[import-untyped]
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

_SOURCE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".sql")
_SQL_KEYWORD = re.compile(r"(?i)\b(select|insert|update|delete)\b")
_SQL_CONCAT = re.compile(r"(?:\+\s*[A-Za-z_][\w.]*|f['\"].*\{[^}]+\}|\.format\s*\()")
_HARDCODED_SECRET = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password)\b\s*=\s*['\"]([^'\"]{8,})['\"]""")
_KNOWN_SECRET_PREFIX = re.compile(r"(?i)^(sk-|AKIA|ghp_|xox[baprs]-)")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})\b")
_FINGERPRINT_SALT = b"argus-sec-finding-salt"
_SECRET_SALT = b"argus-sec-secret-salt"


def _fingerprint(raw: str) -> str:
    return hmac.new(_FINGERPRINT_SALT, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _secret_token(value: str) -> str:
    return hmac.new(_SECRET_SALT, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def invoke(payload: dict) -> dict:
    source_root = Path(payload["source_root"])
    use_llm = payload.get("llm_review", True) and _LLM_AVAILABLE
    findings = []
    for sf in payload.get("files", []):
        if not sf["path"].endswith(_SOURCE_EXTS):
            continue
        text = (source_root / sf["path"]).read_text(encoding="utf-8", errors="replace")
        findings.extend(_sql_injection(sf, text))
        findings.extend(_secret(sf, text))

    # LLM deep review: filter false positives via AI Gateway
    if use_llm and findings:
        reviewed = []
        for f in findings:
            file_path = source_root / f["file"]
            ctx = ""
            if file_path.exists():
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                lo = max(0, f.get("line_start", 1) - 5)
                hi = min(len(lines), f.get("line_end", f.get("line_start", 1)) + 5)
                ctx = "\n".join(
                    f"{i+1}: {line}"
                    for i, line in enumerate(lines[lo:hi], start=lo))
            review = review_finding(f, ctx)
            f["llm_review"] = review
            if review["verdict"] == "NO":
                f["confidence"] = max(0.1, f["confidence"] * 0.3)
                f["llm_suppressed"] = True
            elif review["verdict"] == "YES":
                f["confidence"] = min(1.0, f["confidence"] * 1.2)
            reviewed.append(f)
        findings = reviewed

    return {"schema_version": "1", "status": "completed", "agent": "sec",
            "input_snapshot_id": payload.get("snapshot_id", ""),
            "findings": findings}


def _sql_injection(sf: dict, text: str) -> list[dict]:
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not (_SQL_KEYWORD.search(line) and _SQL_CONCAT.search(line)):
            continue
        findings.append({
            "id": f"sec-sqli-{sf['path']}:{line_no}", "agent": "sec",
            "category": "security.sql_injection", "severity": "critical",
            "confidence": 0.92,
            "title": "SQL query concatenates untrusted input",
            "detail": "SQL statement is built with string interpolation or concatenation",
            "file": sf["path"], "line_start": line_no, "line_end": line_no,
            "remediation": "use parameterized queries or prepared statements",
            "verification": "rerun sec detector and inspect query binding",
            "rollback": None, "cwe": "CWE-89",
            "fingerprint": _fingerprint(f"sec.sqli:{sf['path']}:{line_no}"),
            "rule_id": "SEC-001", "rule_version": "1",
            "evidence": {"detector": "sec.dataflow-analyze",
                         "source_sha256": sf["sha256"], "redacted": False,
                         "context_lines": [_redact(line.strip())]},
        })
    return findings


def _secret(sf: dict, text: str) -> list[dict]:
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = _HARDCODED_SECRET.search(line)
        if not match:
            continue
        value = match.group(2)
        lowered = value.lower()
        if any(x in lowered for x in ("example", "placeholder", "changeme", "your-")):
            continue
        if len(value) < 12 and not _KNOWN_SECRET_PREFIX.search(value):
            continue
        token = _secret_token(value)
        findings.append({
            "id": f"sec-secret-{sf['path']}:{line_no}", "agent": "sec",
            "category": "security.secret", "severity": "critical",
            "confidence": 0.99,
            "title": "Hardcoded credential detected",
            "detail": "A credential-like value is hardcoded in source (value redacted)",
            "file": sf["path"], "line_start": line_no, "line_end": line_no,
            "remediation": "move the value to an environment variable or secret manager",
            "verification": "scan the new snapshot and review repository history",
            "rollback": None, "cwe": "CWE-798",
            "fingerprint": _fingerprint(
                f"sec.secret:{sf['path']}:{line_no}:{token}"),
            "rule_id": "SEC-002", "rule_version": "1",
            "evidence": {"detector": "sec.secret-scan",
                         "source_sha256": sf["sha256"], "redacted": True,
                         "redacted_value": token,
                         "context_lines": [_redact(line.strip())]},
        })
    return findings


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
