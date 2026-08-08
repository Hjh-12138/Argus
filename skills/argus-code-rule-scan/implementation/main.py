#!/usr/bin/env python3
"""argus-code-rule-scan: standalone code auditor.

No host imports. Detects placeholder implementations in source files.
The `acceptance_probe` is accepted only under profile == "phase-one-acceptance".
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

_skill_dir = Path(__file__).resolve().parent.parent
_shared_dir = _skill_dir.parent / "_shared"
if _shared_dir.is_dir():
    sys.path.insert(0, str(_shared_dir))
try:
    from llm_review import review_finding  # type: ignore
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

_SOURCE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs")
_PLACEHOLDER = re.compile(
    r"(?i)(TODO\s*:?\s*implement|FIXME\s*:?\s*implement|"
    r"return\s+['\"]?not\s+implemented|raise\s+NotImplementedError|"
    r"placeholder\s+implementation)"
)
_FINGERPRINT_SALT = b"argus-code-salt"


def _fingerprint(raw: str) -> str:
    return hmac.new(_FINGERPRINT_SALT, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _redact(text: str) -> str:
    return re.sub(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})\b",
                  "[REDACTED]", text)


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
            ctx = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines[lo:hi], start=lo))
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
    profile = payload.get("profile", "")
    acceptance_probe = payload.get("acceptance_probe")
    if acceptance_probe is not None and profile != "phase-one-acceptance":
        raise ValueError("acceptance_probe is not allowed outside the acceptance profile")

    findings = []
    for sf in payload.get("files", []):
        if not sf["path"].endswith(_SOURCE_EXTS):
            continue
        text = (source_root / sf["path"]).read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not _PLACEHOLDER.search(line):
                continue
            excerpt = _redact(line.strip()[:300])
            findings.append({
                "id": f"code-placeholder-{sf['path']}:{line_no}",
                "agent": "code", "category": "code.placeholder",
                "severity": "medium", "confidence": 0.82,
                "title": "Placeholder implementation remains in production code",
                "detail": "A placeholder marker indicates incomplete behavior",
                "file": sf["path"], "line_start": line_no, "line_end": line_no,
                "remediation": "replace the placeholder with a complete implementation",
                "verification": "rerun Code Auditor on the new snapshot",
                "rollback": None, "cwe": None,
                "fingerprint": _fingerprint(
                    f"code.placeholder:{sf['path']}:{line_no}"),
                "rule_id": "CODE-001", "rule_version": "1",
                "evidence": {"detector": "code.placeholder-detect",
                             "source_sha256": sf["sha256"], "redacted": False},
            })

    if acceptance_probe is not None:
        findings.append({
            "id": acceptance_probe.get("id", "acceptance-probe"),
            "agent": "code", "category": "code.placeholder",
            "severity": "medium", "confidence": 0.8,
            "title": "Acceptance hallucination probe",
            "detail": "probe finding injected under acceptance profile",
            "file": acceptance_probe.get("file"), "line_start": 1, "line_end": 1,
            "remediation": "none (probe only)",
            "verification": "acceptance harness verifies removal",
            "rollback": None, "cwe": None,
            "fingerprint": "acceptance-probe-fingerprint",
            "rule_id": "ACCEPT-PROBE", "rule_version": "1",
            "evidence": {"detector": "acceptance.probe",
                         "source_sha256": "0" * 64, "redacted": False},
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
