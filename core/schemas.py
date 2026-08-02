"""Argus v2 core domain schemas.

真相链：snapshot -> detector/rule version -> finding -> meta decision -> policy -> report。
只允许快照内相对 POSIX 路径；critical/high 必须有 file+line_start+evidence。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

SEVERITIES = ("critical", "high", "medium", "low", "info")
AGENTS = ("dep", "arch", "code", "sec", "perf", "robust", "delivery", "atk")

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


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    sha256: str
    size: int
    language: Optional[str] = None


@dataclass(frozen=True)
class SourceSnapshot:
    root: str
    files: tuple[SnapshotFile, ...]
    base_revision: Optional[str] = None
    head_revision: Optional[str] = None
    created_at: Optional[datetime] = None
    snapshot_id: str = ""

    def __post_init__(self):
        if not self.snapshot_id:
            m = hashlib.sha256()
            for f in sorted(self.files, key=lambda x: x.path):
                m.update(f"{f.path}\0{f.sha256}\0{f.size}\0".encode())
            object.__setattr__(self, "snapshot_id", m.hexdigest())


@dataclass(frozen=True)
class AgentResult:
    agent: str
    agent_version_id: str
    status: Literal["completed", "skipped", "timeout", "failed", "cancelled"]
    required: bool
    findings: tuple[Finding, ...]
    input_snapshot_id: str
    rule_set_version: str
    dataset_version: str
    metrics: dict
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    prompt_version: Optional[str] = None
    model_version: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "skipped", "timeout", "failed", "cancelled")


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
