"""argus-finding-emit skill entrypoint."""
from __future__ import annotations

from core.schemas import Evidence, Finding, finding_to_dict


def invoke(payload: dict) -> dict:
    evidence_raw = payload["evidence"]
    evidence = Evidence(
        context_lines=tuple(evidence_raw.get("context_lines", ())),
        source_sha256=evidence_raw.get("source_sha256"),
        redacted_value=evidence_raw.get("redacted_value"),
        detector=evidence_raw.get("detector", ""),
        reasoning_summary=None,
    )
    finding = Finding(
        id=payload.get("id") or payload["fingerprint"][:16],
        agent=payload["agent"], category=payload["category"],
        severity=payload["severity"], confidence=float(payload["confidence"]),
        title=payload["title"], detail=payload["detail"],
        file=payload.get("file"), line_start=payload.get("line_start"),
        line_end=payload.get("line_end"), remediation=payload["remediation"],
        verification=payload["verification"], rollback=payload.get("rollback"),
        cwe=payload.get("cwe"), fingerprint=payload["fingerprint"],
        rule_id=payload["rule_id"], rule_version=payload["rule_version"],
        evidence=evidence,
    )
    return {"status": "succeeded", "finding_id": finding.id,
            "finding": finding_to_dict(finding)}
