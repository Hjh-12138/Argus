#!/usr/bin/env python3
"""argus-ci-policy-check: standalone delivery auditor.

No host imports. Detects CI workflows that build/compile but never run the
repository's test command when the repository contains tests.
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

_TEST_RUN = re.compile(
    r"(?i)\b(pytest|python\s+-m\s+unittest|go\s+test|npm\s+test|pnpm\s+test|"
    r"yarn\s+test|dotnet\s+test|mvn\s+test|gradle\s+test|make\s+test)\b")
_COMPILE_OR_BUILD = re.compile(
    r"(?i)(compileall|tsc\s+--noEmit|go\s+build|npm\s+run\s+build|pnpm\s+build|"
    r"mvn\s+package|gradle\s+build)")
_FINGERPRINT_SALT = b"argus-delivery-salt"


def _fingerprint(raw: str) -> str:
    return hmac.new(_FINGERPRINT_SALT, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _is_ci_path(path: str) -> bool:
    p = path.lower()
    return (
        p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ) or p in (".gitlab-ci.yml", "azure-pipelines.yml")


def _is_test_path(path: str) -> bool:
    p = "/" + path.lower()
    return (
        "/tests/" in p or "/test/" in p or "/__tests__/" in p
        or ".test." in p or ".spec." in p
        or path.lower().startswith(("test_", "tests/", "test/"))
    )


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
    files = payload.get("files", [])
    has_tests = any(_is_test_path(sf["path"]) for sf in files)
    findings = []
    if has_tests:
        for sf in files:
            if not _is_ci_path(sf["path"]):
                continue
            text = (source_root / sf["path"]).read_text(encoding="utf-8", errors="replace")
            if _COMPILE_OR_BUILD.search(text) and not _TEST_RUN.search(text):
                findings.append({
                    "id": f"delivery-testgap-{sf['path']}", "agent": "delivery",
                    "category": "delivery.test_gap", "severity": "medium",
                    "confidence": 0.88,
                    "title": "CI builds the project but does not run tests",
                    "detail": "The repository contains tests, but this CI workflow has no test command",
                    "file": sf["path"], "line_start": 1, "line_end": 1,
                    "remediation": "add the repository's test command to the CI workflow",
                    "verification": "inspect the updated workflow and rerun Delivery Auditor",
                    "rollback": None, "cwe": None,
                    "fingerprint": _fingerprint(f"delivery.testgap:{sf['path']}"),
                    "rule_id": "DEL-001", "rule_version": "1",
                    "evidence": {
                        "detector": "delivery.ci-policy-check",
                        "source_sha256": sf["sha256"], "redacted": False,
                    },
                })
    return {"schema_version": "1", "status": "completed", "agent": "delivery",
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
