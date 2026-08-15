"""AuditReport 物化：report.json + report.md 原子写。

JSON 失败时不得只输出 Markdown 并返回成功（§12）。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from core.meta import MetaDecision
from core.policy import PolicyDecision
from core.redaction import redact
from core.schemas import AgentResult, SourceSnapshot, finding_to_dict


class ReportWriteError(Exception):
    pass


_FORBIDDEN_REPORT_KEYS = {
    "private_reasoning", "reasoning_text", "raw_prompt", "raw_response",
    "source_code", "secret", "api_key",
}


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
        return redact(value)
    return value


def render_report(run_id: str, snapshot: SourceSnapshot,
                  results: tuple[AgentResult, ...],
                  meta_decisions: tuple[MetaDecision, ...],
                  policy: PolicyDecision,
                  coverage=None,
                  attack_verdict: str = "NOT_RUN",
                  not_audited_domains: tuple[str, ...] = ()) -> dict:
    meta_by_id = {d.finding_id: d for d in meta_decisions}
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
        for finding in result.findings:
            decision = meta_by_id.get(finding.id)
            if decision:
                quality_counts[label_key[decision.label]] += 1
            # HALLUCINATION 从主 finding 列表排除，但质量指标保留。
            if decision and decision.label == "HALLUCINATION":
                continue
            item = finding_to_dict(finding)
            item["quality_label"] = decision.label if decision else "NEEDS_EVIDENCE"
            item["quality_reason_codes"] = list(decision.reason_codes) if decision else ["NO_META_DECISION"]
            findings.append(item)

    by_severity = {s: 0 for s in ("critical", "high", "medium", "low", "info")}
    for f in findings:
        by_severity[f["severity"]] += 1

    coverage_dict = {
        "files_total": getattr(coverage, "files_total", len(snapshot.files)),
        "files_scanned": getattr(coverage, "files_scanned", len(snapshot.files)),
        "files_skipped": (
            getattr(coverage, "files_total", len(snapshot.files))
            - getattr(coverage, "files_scanned", len(snapshot.files))
        ),
        "skip_reasons": getattr(coverage, "skip_reasons", {}),
        "agents_required": sorted(r.agent for r in results if r.required),
        "agents_completed": sorted(r.agent for r in results if r.status == "completed"),
        "agents_not_audited": sorted(not_audited_domains),
    }

    return {
        "schema_version": "2.0",
        "run_id": run_id,
        "run_status": "completed" if policy.release_gate != "unknown" else "partial",
        "release_gate": policy.release_gate,
        "attack_verdict": attack_verdict,
        "target": {
            "source_path": "<local-redacted>",
            "snapshot_id": snapshot.snapshot_id,
            "base_revision": snapshot.base_revision,
            "head_revision": snapshot.head_revision,
        },
        "versions": {
            "argus": "2.0.0",
            "config_schema": 1,
            "rules": "2026.08.02",
            "agents": {r.agent: r.agent_version_id for r in results},
        },
        "coverage": coverage_dict,
        "summary": {
            "total_findings": len(findings),
            "blocking_findings": len(policy.blocking_finding_ids),
            "by_severity": by_severity,
            "meta_quality": quality_counts,
            "suppressed": 0,
        },
        "findings": findings,
        "agent_results": [
            {
                "agent": r.agent, "status": r.status, "required": r.required,
                "agent_version_id": r.agent_version_id, "finding_count": len(r.findings),
                "error_code": r.error_code, "error_message": r.error_message,
                "metrics": r.metrics,
            } for r in results
        ],
        "meta_decisions": [asdict(d) for d in meta_decisions],
        "policy_decisions": [asdict(policy)],
        "errors": [
            {"agent": r.agent, "code": r.error_code, "message": r.error_message}
            for r in results if r.error_code
        ],
    }


def write_report(output_dir: str | Path, data: dict) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    sanitized = _sanitize_report_value(data)
    json_tmp = _write_temp(
        out, json.dumps(sanitized, ensure_ascii=False, indent=2))
    # 在发布前回读并校验 JSON 可解析、关键字段存在。
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


def _write_temp(directory: Path, text: str) -> Path:
    fd, path = tempfile.mkstemp(dir=directory, suffix=".tmp")
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


def _render_md(data: dict) -> str:
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
    for finding in data["findings"]:
        loc = finding.get("file") or "project"
        if finding.get("line_start"):
            loc += f":{finding['line_start']}"
        lines.extend([
            f"### [{finding['severity'].upper()}] {finding['title']}", "",
            f"- Location: `{loc}`",
            f"- Agent: `{finding['agent']}`",
            f"- Quality: `{finding['quality_label']}`",
            f"- Confidence: {finding['confidence']:.2f}",
            f"- Remediation: {finding['remediation']}",
            f"- Verification: {finding['verification']}", "",
        ])
    lines.extend(["## Coverage & Limitations", "",
                  f"- Files scanned: {data['coverage']['files_scanned']}/{data['coverage']['files_total']}",
                  f"- Agents completed: {', '.join(data['coverage']['agents_completed'])}", "",
                  "## Reproduction Metadata", "",
                  f"- Argus: {data['versions']['argus']}",
                  f"- Rules: {data['versions']['rules']}",
                  f"- Snapshot: `{data['target']['snapshot_id']}`", ""])
    return "\n".join(lines)
