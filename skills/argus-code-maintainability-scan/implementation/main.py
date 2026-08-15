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
