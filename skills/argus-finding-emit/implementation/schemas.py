"""Self-contained schemas for argus-finding-emit — no host `core` dependency.

These mirror the subset of `core/schemas.py` that the finding-emit contract
needs (Evidence, Finding, finding_to_dict), vendored so the skill runs in the
isolated worker sandbox where the host `core` package is absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SEVERITIES = ("critical", "high", "medium", "low", "info")
Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class Evidence:
    """finding 的最小可复核证据。reasoning_summary 禁止保存模型私有推理。"""

    context_lines: tuple[str, ...] = ()
    source_sha256: Optional[str] = None
    redacted_value: Optional[str] = None
    detector: str = ""
    reasoning_summary: Optional[str] = None


@dataclass(frozen=True)
class Finding:
    id: str
    agent: str
    category: str
    severity: Severity
    confidence: float
    title: str
    detail: str
    remediation: str
    verification: str
    fingerprint: str
    rule_id: str
    rule_version: str
    evidence: Optional[Evidence]
    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    rollback: Optional[str] = None
    cwe: Optional[str] = None

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity {self.severity}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.file is not None:
            p = self.file.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or ":" in p or p.startswith(".."):
                raise ValueError(f"unsafe path {self.file!r}")
        if self.severity in ("critical", "high") and not (
            self.file and self.line_start and self.evidence
        ):
            raise ValueError("critical/high need file+line_start+evidence")


def finding_to_dict(f) -> dict:
    return {
        "id": f.id, "agent": f.agent, "category": f.category, "severity": f.severity,
        "confidence": f.confidence, "title": f.title, "detail": f.detail,
        "file": f.file, "line_start": f.line_start, "line_end": f.line_end,
        "fingerprint": f.fingerprint, "rule_id": f.rule_id, "rule_version": f.rule_version,
        "remediation": f.remediation, "verification": f.verification,
        "rollback": f.rollback, "cwe": f.cwe,
        "evidence": {
            "detector": f.evidence.detector if f.evidence else None,
            "source_sha256": f.evidence.source_sha256 if f.evidence else None,
            "redacted": bool(f.evidence and f.evidence.redacted_value),
        },
    }
