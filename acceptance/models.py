"""Acceptance test data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AcceptanceItem:
    id: str
    status: str  # "PASS", "FAIL", "BLOCKED"
    detail: str = ""


@dataclass
class AcceptanceReport:
    run_id: str
    phase_one: str = ""  # "accepted" or "rejected"
    items: list[AcceptanceItem] = field(default_factory=list)
    accepted_at: str = ""
    evidence_path: str = ""
