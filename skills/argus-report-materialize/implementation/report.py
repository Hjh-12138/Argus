"""Audit Report materialization — self-contained edition.

Atomically writes report.json + report.md from findings, meta decisions,
and policy decision. All processing is dict-based; no external core imports.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class ReportWriteError(Exception):
    pass


_FORBIDDEN_REPORT_KEYS = {
    "private_reasoning", "reasoning_text", "raw_prompt", "raw_response",
    "source_code", "secret", "api_key",
}

# Simple secret pattern redaction
import re as _re
_SECRET_PATTERN = _re.compile(
    r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})\b")


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def _sanitize_report_value(value):
    if isinstance(value, dict):
        return {
            key: _sanitize_report_value(item)
            for key, item in value.items()
            if str(key).lower() not in _FORBIDDEN_REPORT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_report_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_report_value(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def render_report(run_id, snapshot, results, meta_decisions, policy,
                  coverage=None, attack_verdict="NOT_RUN"):
    """Render an audit report dict from dict-based inputs.

    All inputs are plain dicts (parsed from JSON), not dataclass objects.
    """
    meta_by_id = {d["finding_id"]: d for d in meta_decisions}
    findings = []
    quality_counts = {
        "verified": 0, "needs_evidence": 0, "hallucination": 0,
        "inconsistent": 0, "not_actionable": 0,
    }
    label_key = {
        "VERIFIED": "verified", "NEEDS_EVIDENCE": "needs_evidence",
        "HALLUCINATION": "hallucination", "INCONSISTENT": "inconsistent",
        "NOT_ACTIONABLE": "not_actionable",
    }
    for result in results:
        for finding in result.get("findings", []):
            decision = meta_by_id.get(finding["id"])
            if decision:
                quality_counts[label_key[decision["label"]]] += 1
            if decision and decision["label"] == "HALLUCINATION":
                continue
            item = dict(finding)
            item["quality_label"] = decision["label"] if decision else "NEEDS_EVIDENCE"
            item["quality_reason_codes"] = (
                list(decision["reason_codes"]) if decision else ["NO_META_DECISION"]
            )
            findings.append(item)

    by_severity = {s: 0 for s in ("critical", "high", "medium", "low", "info")}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in by_severity:
            by_severity[sev] += 1

    snapshot_files = snapshot.get("files", [])
    files_scanned = getattr(coverage, "files_scanned", len(snapshot_files)) if coverage else len(snapshot_files)
    coverage_dict = {
        "files_total": len(snapshot_files),
        "files_scanned": files_scanned,
        "files_skipped": len(snapshot_files) - files_scanned,
        "skip_reasons": getattr(coverage, "skip_reasons", {}) if coverage else {},
        "agents_required": sorted(r["agent"] for r in results if r.get("required")),
        "agents_completed": sorted(r["agent"] for r in results if r.get("status") == "completed"),
    }

    return {
        "schema_version": "2.0",
        "run_id": run_id,
        "run_status": "completed" if policy.get("release_gate") != "unknown" else "partial",
        "release_gate": policy.get("release_gate", "unknown"),
        "attack_verdict": attack_verdict,
        "target": {
            "source_path": "<local-redacted>",
            "snapshot_id": snapshot.get("snapshot_id", ""),
            "base_revision": snapshot.get("base_revision"),
            "head_revision": snapshot.get("head_revision"),
        },
        "versions": {
            "argus": "2.0.0",
            "config_schema": 1,
            "rules": "2026.08.02",
            "agents": {r["agent"]: r.get("agent_version_id", "") for r in results},
        },
        "coverage": coverage_dict,
        "summary": {
            "total_findings": len(findings),
            "blocking_findings": len(policy.get("blocking_finding_ids", [])),
            "by_severity": by_severity,
            "meta_quality": quality_counts,
            "suppressed": 0,
        },
        "findings": findings,
        "agent_results": [
            {
                "agent": r["agent"], "status": r.get("status", ""),
                "required": r.get("required", True),
                "agent_version_id": r.get("agent_version_id", ""),
                "finding_count": len(r.get("findings", [])),
                "error_code": r.get("error_code"),
                "error_message": r.get("error_message"),
                "metrics": r.get("metrics", {}),
            } for r in results
        ],
        "meta_decisions": list(meta_decisions),
        "policy_decisions": [policy],
        "errors": [
            {"agent": r["agent"], "code": r.get("error_code"),
             "message": r.get("error_message")}
            for r in results if r.get("error_code")
        ],
    }


def write_report(output_dir, data):
    """Write report.json and report.md atomically. Input `data` is a plain dict."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    sanitized = _sanitize_report_value(data)
    json_tmp = _write_temp(out, json.dumps(sanitized, ensure_ascii=False, indent=2))
    try:
        parsed = json.loads(json_tmp.read_text(encoding="utf-8"))
        for key in ("schema_version", "run_id", "run_status", "release_gate", "findings"):
            if key not in parsed:
                raise ReportWriteError(f"report missing required key: {key}")
        md_tmp = _write_temp(out, _render_md(parsed))
        os.replace(json_tmp, json_path)
        os.replace(md_tmp, md_path)
    except Exception as exc:
        json_tmp.unlink(missing_ok=True)
        raise ReportWriteError(str(exc)) from exc
    return json_path, md_path


def _write_temp(directory, text):
    fd, path = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    p = Path(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        return p
    except Exception:
        p.unlink(missing_ok=True)
        raise


def _render_md(data):
    lines = [
        "# Argus Audit Report", "",
        f"**Release Gate: {data['release_gate']}**",
        f"**Run Status: {data['run_status']}**",
        f"**Run: {data['run_id']}**",
        f"**Snapshot: {data['target']['snapshot_id']}**", "",
        "## Policy Reasons", "",
    ]
    policy = data.get("policy_decisions", [{}])[0]
    for reason in policy.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "## Technical Findings", ""])
    for finding in data.get("findings", []):
        loc = finding.get("file") or "project"
        if finding.get("line_start"):
            loc += f":{finding['line_start']}"
        lines.extend([
            f"### [{finding.get('severity', '?').upper()}] {finding.get('title', 'Untitled')}", "",
            f"- Location: `{loc}`",
            f"- Agent: `{finding.get('agent', '?')}`",
            f"- Quality: `{finding.get('quality_label', '?')}`",
            f"- Confidence: {finding.get('confidence', 0):.2f}",
            f"- Remediation: {finding.get('remediation', 'N/A')}",
            f"- Verification: {finding.get('verification', 'N/A')}", "",
        ])
    lines.extend([
        "## Coverage & Limitations", "",
        f"- Files scanned: {data['coverage']['files_scanned']}/{data['coverage']['files_total']}",
        f"- Agents completed: {', '.join(data['coverage']['agents_completed'])}", "",
        "## Reproduction Metadata", "",
        f"- Argus: {data['versions']['argus']}",
        f"- Rules: {data['versions']['rules']}",
        f"- Snapshot: `{data['target']['snapshot_id']}`", "",
    ])
    return "\n".join(lines)
