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
    accepted: str = ""  # ISO timestamp of acceptance
    generated_at: str = ""
    accepted_at: str = ""
    evidence_path: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "phase_one": self.phase_one,
            "accepted": self.accepted,
            "generated_at": self.generated_at,
            "items": [
                {"id": i.id, "status": i.status, "detail": i.detail}
                for i in self.items
            ],
        }
