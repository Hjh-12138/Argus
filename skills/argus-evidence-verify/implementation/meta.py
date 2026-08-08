"""Meta Evidence Quality Gate — self-contained edition.

Meta 只验证 finding，不发现新问题，不修改原事实/severity，不凭空补证据。
质量标签：VERIFIED / NEEDS_EVIDENCE / INCONSISTENT / HALLUCINATION / NOT_ACTIONABLE。

All domain types are inlined so the skill has zero external dependencies
and runs deterministically inside the Worker sandbox.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

# ── Inlined domain types (minimal — only fields MetaReviewer accesses) ──────

SEVERITIES = ("critical", "high", "medium", "low", "info")
Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class Evidence:
    context_lines: tuple[str, ...] = ()
    source_sha256: Optional[str] = None
    redacted_value: Optional[str] = None
    detector: str = ""


@dataclass(frozen=True)
class Finding:
    id: str
    agent: str = ""
    category: str = ""
    severity: Severity = "info"
    confidence: float = 0.0
    title: str = ""
    detail: str = ""
    remediation: str = ""
    verification: str = ""
    fingerprint: str = ""
    rule_id: str = ""
    rule_version: str = ""
    evidence: Optional[Evidence] = None
    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    rollback: Optional[str] = None
    cwe: Optional[str] = None

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity {self.severity}")
        if self.file is not None:
            p = self.file.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or ":" in p:
                raise ValueError(f"unsafe path {self.file!r}")


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    sha256: str
    size: int = 0
    language: Optional[str] = None


@dataclass(frozen=True)
class SourceSnapshot:
    root: str
    files: tuple[SnapshotFile, ...]
    snapshot_id: str = ""


@dataclass(frozen=True)
class AgentResult:
    agent: str = ""
    agent_version_id: str = ""
    status: Literal["completed", "skipped", "timeout", "failed", "cancelled"] = "completed"
    required: bool = True
    findings: tuple[Finding, ...] = ()
    input_snapshot_id: str = ""
    rule_set_version: str = ""
    dataset_version: str = ""
    metrics: dict | None = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.metrics is None:
            object.__setattr__(self, "metrics", {})


# ── MetaReviewer ────────────────────────────────────────────────────────────

QualityLabel = Literal[
    "VERIFIED", "NEEDS_EVIDENCE", "INCONSISTENT", "HALLUCINATION", "NOT_ACTIONABLE"
]


@dataclass(frozen=True)
class MetaDecision:
    finding_id: str
    label: QualityLabel
    reason_codes: tuple[str, ...]
    detail: str
    checked_source_sha256: str | None = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class MetaReviewer:
    """对 AgentResult 的 path/line/hash/evidence/actionability 做独立校验。"""

    def review(self, snapshot: SourceSnapshot,
               results: tuple[AgentResult, ...] | list[AgentResult]) -> tuple[MetaDecision, ...]:
        decisions: list[MetaDecision] = []
        snapshot_files = {f.path: f for f in snapshot.files}
        for result in results:
            for finding in result.findings:
                decisions.append(self._decide(snapshot, snapshot_files, finding))
        return tuple(decisions)

    def _decide(self, snapshot: SourceSnapshot, snapshot_files: dict,
                finding: Finding) -> MetaDecision:
        if finding.file is None:
            if finding.evidence and finding.evidence.detector:
                return self._actionability(finding, checked_sha=None)
            return MetaDecision(finding.id, "NEEDS_EVIDENCE",
                                ("MANIFEST_EVIDENCE_MISSING",),
                                "project-level finding lacks manifest evidence")

        sf = snapshot_files.get(finding.file)
        if sf is None:
            return MetaDecision(finding.id, "HALLUCINATION",
                                ("PATH_NOT_IN_SNAPSHOT",),
                                f"path {finding.file!r} is not present in snapshot")

        file_path = Path(snapshot.root) / finding.file
        if not file_path.exists():
            return MetaDecision(finding.id, "HALLUCINATION",
                                ("PATH_NOT_READABLE",),
                                f"snapshot path {finding.file!r} cannot be read")

        actual_sha = _sha256(file_path)
        if actual_sha != sf.sha256:
            return MetaDecision(finding.id, "NEEDS_EVIDENCE",
                                ("SNAPSHOT_HASH_MISMATCH",),
                                "source changed after snapshot; rerun on a new snapshot",
                                checked_source_sha256=actual_sha)

        if finding.evidence and finding.evidence.source_sha256:
            if finding.evidence.source_sha256 != sf.sha256:
                return MetaDecision(finding.id, "HALLUCINATION",
                                    ("EVIDENCE_HASH_MISMATCH",),
                                    "finding evidence hash does not match snapshot",
                                    checked_source_sha256=actual_sha)

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if finding.line_start is not None:
            line_end = finding.line_end or finding.line_start
            if finding.line_start < 1 or line_end < finding.line_start or line_end > len(lines):
                return MetaDecision(finding.id, "HALLUCINATION",
                                    ("LINE_OUT_OF_RANGE",),
                                    f"line range {finding.line_start}-{line_end} outside file",
                                    checked_source_sha256=actual_sha)

        if finding.severity in ("critical", "high"):
            if not finding.evidence or not finding.evidence.context_lines:
                return MetaDecision(finding.id, "NEEDS_EVIDENCE",
                                    ("EVIDENCE_INSUFFICIENT",),
                                    "critical/high finding requires context evidence",
                                    checked_source_sha256=actual_sha)

        return self._actionability(finding, checked_sha=actual_sha)

    def _actionability(self, finding: Finding, checked_sha: str | None) -> MetaDecision:
        if not finding.remediation.strip():
            return MetaDecision(finding.id, "NOT_ACTIONABLE",
                                ("REMEDIATION_MISSING",),
                                "finding has no concrete remediation",
                                checked_source_sha256=checked_sha)
        if not finding.verification.strip():
            return MetaDecision(finding.id, "NOT_ACTIONABLE",
                                ("VERIFICATION_MISSING",),
                                "finding has no verification method",
                                checked_source_sha256=checked_sha)
        return MetaDecision(finding.id, "VERIFIED", ("OK",),
                            "path/line/hash/evidence/actionability consistent",
                            checked_source_sha256=checked_sha)
