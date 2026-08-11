"""Role-specific Task input packages referencing the immutable snapshot.

Matrix and Task metadata never carry source bytes; only snapshot references,
file digests, and role-only fixtures travel in the input payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLE_SKILLS = {
    "dep": "argus-dependency-inspect",
    "code": "argus-code-rule-scan",
    "sec": "argus-secret-scan",
    "delivery": "argus-ci-policy-check",
    "meta": "argus-evidence-verify",
    "synth": "argus-release-policy-evaluate",
}

ASSESSORS = ("dep", "code", "sec", "delivery")
CORE_AGENTS = (*ASSESSORS, "meta", "synth")
WORKER_RUNTIME = "openclaw"
WORKER_IMAGE = "agentteams/worker-agent:v1.2.0-beta.1-argus.7"


@dataclass(frozen=True)
class WorkerDefinition:
    agent: str
    name: str
    role: str
    skills: tuple[str, ...]


WORKERS: dict[str, WorkerDefinition] = {
    "dep": WorkerDefinition(
        "dep", "argus-dep",
        "Dependency auditor. Validate manifests and registry evidence without installing dependencies.",
        ("argus-dependency-inspect", "argus-finding-emit"),
    ),
    "code": WorkerDefinition(
        "code", "argus-code",
        "Code auditor. Validate correctness and state contracts without executing target code.",
        ("argus-code-rule-scan", "argus-finding-emit"),
    ),
    "sec": WorkerDefinition(
        "sec", "argus-sec",
        "Security auditor. Validate static security evidence and never emit raw secrets.",
        ("argus-secret-scan", "argus-finding-emit"),
    ),
    "delivery": WorkerDefinition(
        "delivery", "argus-delivery",
        "Delivery auditor. Validate CI and release evidence without triggering CI or deployment.",
        ("argus-ci-policy-check", "argus-finding-emit"),
    ),
    "meta": WorkerDefinition(
        "meta", "argus-meta",
        "Evidence quality gate. Verify evidence only; never create findings or decide the release gate.",
        ("argus-evidence-verify",),
    ),
    "synth": WorkerDefinition(
        "synth", "argus-synth",
        "Audit synthesizer. Consume Meta-reviewed artifacts and apply deterministic release policy.",
        ("argus-release-policy-evaluate", "argus-report-materialize"),
    ),
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
        # Top-level source_root is required by the executor's
        # extractSnapshotInputs() to unzip the snapshot archive before the
        # skill runs. Without it, meta skills see no files → PATH_NOT_READABLE.
        "source_root": snapshot.source_root,
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
        # Required by extractSnapshotInputs() for snapshot extraction.
        "source_root": snapshot.source_root,
        "output_dir": ".",
        "snapshot": {"snapshot_id": snapshot.snapshot_id},
        "agent_results": assessor_artifacts,
        "meta_decisions": decisions,
        "policy": policy,
    }
