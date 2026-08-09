"""Role-specific Task input packages referencing the immutable snapshot.

Matrix and Task metadata never carry source bytes; only snapshot references,
file digests, and role-only fixtures travel in the input payload.
"""
from __future__ import annotations

from dataclasses import dataclass

ROLE_SKILLS = {
    "dep": "argus-dependency-inspect",
    "code": "argus-code-rule-scan",
    "sec": "argus-secret-scan",
    "delivery": "argus-ci-policy-check",
    "meta": "argus-evidence-verify",
    "synth": "argus-release-policy-evaluate",
}


@dataclass(frozen=True)
class SnapshotReference:
    snapshot_id: str
    source_root: str
    files: tuple[dict, ...]
    archive_path: str
    archive_sha256: str


def assessor_payload(role: str, run_id: str, snapshot: SnapshotReference,
                     registry: dict | None = None,
                     profile: str = "", acceptance_probe: dict | None = None) -> dict:
    """Input payload for a deterministic assessor Skill."""
    payload: dict = {
        "schema_version": "1",
        "run_id": run_id,
        "snapshot_id": snapshot.snapshot_id,
        "source_root": snapshot.source_root,
        "files": list(snapshot.files),
    }
    if role == "dep" and registry is not None:
        payload["registry"] = registry
    if role == "code":
        payload["profile"] = profile
        if acceptance_probe is not None:
            payload["acceptance_probe"] = acceptance_probe
    return payload


def meta_payload(run_id: str, snapshot: SnapshotReference,
                 assessor_artifacts: list[dict]) -> dict:
    """Meta input references the four assessor machine artifacts by digest."""
    return {
        "schema_version": "1",
        "run_id": run_id,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot": {
            "root": snapshot.source_root,
            "files": list(snapshot.files),
            "snapshot_id": snapshot.snapshot_id,
        },
        "agent_results": assessor_artifacts,
    }


def synth_payload(run_id: str, snapshot: SnapshotReference,
                  assessor_artifacts: list[dict],
                  decisions: list[dict], policy: dict) -> dict:
    """Synth input references reviewed artifacts, decisions and policy config."""
    return {
        "schema_version": "1",
        "run_id": run_id,
        "snapshot_id": snapshot.snapshot_id,
        "output_dir": ".",
        "snapshot": {"snapshot_id": snapshot.snapshot_id},
        "agent_results": assessor_artifacts,
        "meta_decisions": decisions,
        "policy": policy,
    }
