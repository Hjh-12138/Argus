#!/usr/bin/env python3
"""argus-dependency-inspect: standalone dependency auditor.

No host imports. Parses direct dependencies from manifest files in the
snapshot and compares against a typed registry fixture. A registry entry that
is absent or unverified never produces a finding; only explicit
exists=false does.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

# Make _shared/llm_review importable from the skill sandbox
_skill_dir = Path(__file__).resolve().parent.parent
_shared_dir = _skill_dir.parent / "_shared"
if _shared_dir.is_dir():
    sys.path.insert(0, str(_shared_dir))
try:
    from llm_review import review_finding  # type: ignore
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

_MANIFEST_PARSERS = {
    "pyproject.toml": "pyproject",
    "requirements.txt": "requirements",
    "requirements.in": "requirements",
    "package.json": "package_json",
    "go.mod": "go_mod",
}
_PEP508 = re.compile(
    r"""^\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*"""
    r"""(==|>=|<=|~=|!=|>|<)?\s*([^\s,;]+)?"""
)
_JSON_KEY_RE = re.compile(r'"([^"]+)"\s*:\s*"([^"]*)"')
_FINGERPRINT_SALT = b"argus-dep-salt"


def _fingerprint(raw: str) -> str:
    return hmac.new(_FINGERPRINT_SALT, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _parse(text: str, parser: str):
    if parser == "requirements":
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-", "git+", "http")):
                continue
            match = _PEP508.match(line)
            if match:
                yield match.group(1), match.group(2) or "any"
    elif parser == "pyproject":
        array = re.search(r"(?s)dependencies\s*=\s*\[(.*?)\]", text)
        if array:
            for quoted in re.findall(r"['\"]([^'\"]+)['\"]", array.group(1)):
                match = _PEP508.match(quoted)
                if match:
                    yield match.group(1), (match.group(2) or "") + (match.group(3) or "") or "any"
    elif parser == "package_json":
        for key, value in _JSON_KEY_RE.findall(text):
            if key in ("dependencies", "devDependencies", "peerDependencies"):
                _ = value
    elif parser == "go_mod":
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^\s*([A-Za-z0-9_./-]+)\s+v([0-9][^\s]*)", line)
            if match and not stripped.startswith(("module", "go ")):
                yield match.group(1), match.group(2)


def _llm_review_findings(findings: list, source_root: Path) -> list:
    """Optionally run LLM deep review on findings."""
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
    registry = payload.get("registry", {}) or {}
    findings = []
    for sf in payload.get("files", []):
        parser = _MANIFEST_PARSERS.get(sf["path"].split("/")[-1])
        if parser is None:
            continue
        text = (source_root / sf["path"]).read_text(encoding="utf-8", errors="replace")
        for name, spec in _parse(text, parser):
            entry = registry.get(name)
            if entry is None:
                continue
            if entry.get("exists") is False:
                findings.append({
                    "id": f"dep-nonexistent-{sf['path']}-{name}",
                    "agent": "dep", "category": "dependency.nonexistent",
                    "severity": "high" if ">=" in spec else "medium",
                    "confidence": 0.98,
                    "title": f"dependency not found: {name}",
                    "detail": f"'{name}' is not present in the registry fixture",
                    "file": sf["path"], "line_start": 1, "line_end": 1,
                    "remediation": f"remove or replace dependency '{name}'",
                    "verification": "rerun dep detector against fixed manifest",
                    "rollback": None, "cwe": None,
                    "fingerprint": _fingerprint(f"dep.nonexistent:{name}"),
                    "rule_id": "DEP-001", "rule_version": "1",
                    "evidence": {
                        "detector": "dep.registry-verify",
                        "source_sha256": sf["sha256"],
                        "redacted": False,
                        "context_lines": [f"declares dependency {name} (spec {spec})"],
                    },
                })
    return {"schema_version": "1", "status": "completed", "agent": "dep",
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
