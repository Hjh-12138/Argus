"""Real AgentTeams audit Project DAG driver.

Registers assessor -> Meta -> revision/recheck -> Synth typed Tasks through the
fork Task protocol, validates machine artifacts, and materializes a gate. A
required Task failure, timeout, conflict, missing artifact, or Skill identity
mismatch can never produce pass.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.protocol import (
    ProtocolError, TERMINAL_STATES, TaskState, parse_envelope, parse_record,
)
from agentteams.worker_payloads import (
    ROLE_SKILLS, SnapshotReference, assessor_payload, meta_payload, synth_payload,
)

ASSESSOR_ROLES = ("dep", "code", "sec", "delivery")
PROJECT_WORKERS = tuple(
    f"argus-{role}" for role in (*ASSESSOR_ROLES, "meta", "synth")
)
TERMINAL_OK = {TaskState.COMPLETED.value}
REVISION_LIMIT = 2


@dataclass
class ProjectOutcome:
    project_id: str
    status: str
    task_states: dict[str, str] = field(default_factory=dict)
    gate: str = "unknown"
    report_paths: list[str] = field(default_factory=list)
    error: str = ""


class ProjectDriver:
    def __init__(self, client: HiclawClient, workspace: Path,
                 *, ack_timeout_s: int = 60, run_timeout_s: int = 600):
        self.client = client
        self.workspace = Path(workspace).resolve()
        self.ack_timeout_s = ack_timeout_s
        self.run_timeout_s = run_timeout_s
        self._lock = self._load_lock()

    def _load_lock(self) -> dict:
        lock_path = self.workspace / "skills" / "skills.lock.json"
        return json.loads(lock_path.read_text(encoding="utf-8"))

    def _skill_version(self, name: str) -> str:
        for item in self._lock.get("skills", []):
            if item["name"] == name:
                return str(item["version"])
        raise HiclawError(f"skill {name} not in lock")

    def _worker_for(self, role: str) -> str:
        assignment = {f"argus-{r}": r for r in ASSESSOR_ROLES}
        return f"argus-{role}"

    def _skill_identity(self, worker: str, skill: str) -> tuple[str, str]:
        """Resolve the Worker's observed remote-Skill generation and digest.

        The Controller validates a task's skill_generation against the Worker's
        active observed generation, so Argus must send the generation the Worker
        actually converged on, never a snapshot-derived id.
        """
        observation = self.client.get_worker_skill_observation(worker)
        generation = str(observation.get("generation", ""))
        digest = ""
        for entry in observation.get("skills", []):
            if entry.get("name") == skill:
                digest = str(entry.get("observed_digest", ""))
                break
        if not generation or not digest.startswith("sha256:"):
            raise HiclawError(
                f"skill {skill} not observed-ready on {worker}: "
                f"generation={generation!r} digest={digest!r}")
        return generation, digest

    def _register_task(self, project_id: str, room_id: str, task_id: str,
                       worker: str, kind: str, skill: str,
                       snapshot: SnapshotReference,
                       input_payload: dict, deadline_offset_s: int = 600,
                       required: bool = True) -> dict:
        from datetime import datetime, timedelta, timezone
        generation, digest = self._skill_identity(worker, skill)
        envelope = {
            "schema_version": "1",
            "task_id": task_id,
            "project_id": project_id,
            "room_id": room_id,
            "assigned_worker": worker,
            "kind": kind,
            "attempt": 1,
            "deadline": (datetime.now(timezone.utc) +
                         timedelta(seconds=deadline_offset_s)).isoformat().replace("+00:00", "Z"),
            "skill": skill,
            "skill_version": self._skill_version(skill),
            "skill_generation": generation,
            "skill_digest": digest,
            "agent_version": "argus-v1",
            "inputs": [{"path": f"shared/projects/{project_id}/snapshot.zip",
                        "sha256": snapshot.archive_sha256}],
            "input_payload": input_payload,
            "output_schema": f"skills/{skill}/schemas/output.schema.json",
            "idempotency_key": "",
            "required": required,
        }
        # Compute the same idempotency key the Controller will require.
        envelope["idempotency_key"] = self._idempotency_key(envelope)
        return self.client.register_task(envelope)

    def _publish_snapshot(self, project_id: str,
                          snapshot: SnapshotReference) -> None:
        archive = Path(snapshot.archive_path).resolve()
        if not archive.is_file():
            raise HiclawError(f"snapshot archive missing: {archive}")
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        expected = snapshot.archive_sha256.removeprefix("sha256:")
        if actual != expected:
            raise HiclawError(
                "snapshot archive digest mismatch: "
                f"expected={expected} actual={actual}")
        self.client.publish_shared_file(
            f"projects/{project_id}/snapshot.zip", archive)
        self.client.publish_shared_text(
            f"projects/{project_id}/snapshot.id",
            json.dumps({"snapshot_id": snapshot.snapshot_id,
                        "archive_sha256": snapshot.archive_sha256}),
        )

    def _idempotency_key(self, envelope: dict) -> str:
        parts = [
            envelope["project_id"], envelope["task_id"], str(envelope["attempt"]),
            envelope["skill"], envelope["skill_version"],
            envelope["skill_generation"], envelope["skill_digest"],
            envelope["agent_version"],
        ]
        for inp in sorted(envelope["inputs"], key=lambda i: i["path"]):
            parts.extend([inp["path"], inp["sha256"]])
        digest = hashlib.sha256()
        for part in parts:
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()

    def _dispatch_and_wait(self, task_id: str) -> dict:
        record = self.client.get_task(task_id)["task"]
        record = self.client.dispatch_task(task_id, record["revision"])
        return self.client.wait_task(task_id, {s.value for s in TERMINAL_STATES},
                                     timeout_s=self.run_timeout_s)

    def _artifact(self, task_id: str) -> dict | None:
        try:
            shared = self.client.pull_shared_directory(f"tasks/{task_id}")
            _ = shared
        except HiclawError:
            return None
        try:
            text = self.client.read_shared_text(f"tasks/{task_id}/artifacts/result.json")
            return json.loads(text)
        except HiclawError:
            return None

    def run(self, request: dict, snapshot: SnapshotReference,
            registry: dict | None = None,
            profile: str = "", acceptance_probe: dict | None = None) -> ProjectOutcome:
        project_id = request.get("project_id") or f"argus-{uuid.uuid4().hex[:12]}"
        run_id = request.get("run_id", project_id)
        title = request.get("title") or f"Argus audit {run_id}"
        task_states: dict[str, str] = {}
        artifacts: list[dict] = []

        project = self.client.create_project(project_id, title, PROJECT_WORKERS)
        room_id = project.get("project_room_id")
        if not isinstance(room_id, str) or not room_id:
            raise HiclawError("AgentTeams project has no Project Room")
        # Point the assessor Skills at the per-project snapshot directory the
        # typed executor will extract the archive into, so they never read
        # unextracted or colliding files from the shared root.
        snapshot = replace(
            snapshot,
            source_root=f"/root/hiclaw-fs/shared/projects/{project_id}/snapshot",
        )
        self._publish_snapshot(project_id, snapshot)

        for role in ASSESSOR_ROLES:
            task_id = f"{project_id}-assessor-{role}"
            skill = ROLE_SKILLS[role]
            payload = assessor_payload(role, run_id, snapshot, registry,
                                       profile, acceptance_probe if role == "code" else None)
            self._register_task(
                project_id, room_id, task_id, self._worker_for(role),
                "assess", skill, snapshot, payload)
            record = self._dispatch_and_wait(task_id)
            task_states[task_id] = record["state"]
            artifact = self._artifact(task_id)
            if record["state"] != "COMPLETED":
                return ProjectOutcome(
                    project_id=project_id, status="human-wait",
                    task_states=task_states,
                    error=f"required assessor {role} not completed: {record['state']}")
            if artifact is None:
                return ProjectOutcome(
                    project_id=project_id, status="human-wait",
                    task_states=task_states,
                    error=f"required assessor {role} missing machine artifact")
            artifacts.append(artifact)

        meta_id = f"{project_id}-meta"
        self._register_task(project_id, room_id, meta_id, "argus-meta", "meta",
                            "argus-evidence-verify", snapshot,
                            meta_payload(run_id, snapshot, artifacts))
        meta_record = self._dispatch_and_wait(meta_id)
        task_states[meta_id] = meta_record["state"]
        meta_artifact = self._artifact(meta_id)
        if meta_record["state"] != "COMPLETED" or meta_artifact is None:
            return ProjectOutcome(project_id=project_id, status="human-wait",
                                  task_states=task_states,
                                  error="meta task failed or artifact missing")
        decisions = meta_artifact.get("decisions", [])
        hallucinated = [d for d in decisions if d.get("label") == "HALLUCINATION"]
        if hallucinated:
            revision_outcome = self._revision_loop(
                project_id, room_id, task_states, snapshot, decisions, artifacts)
            if revision_outcome is not None:
                return revision_outcome

        synth_id = f"{project_id}-synth"
        policy = {"require_quality_label": "VERIFIED", "min_confidence": 0.8,
                  "block_on": ["critical", "high"]}
        self._register_task(project_id, room_id, synth_id, "argus-synth", "synth",
                            "argus-release-policy-evaluate", snapshot,
                            synth_payload(run_id, snapshot, artifacts, decisions, policy))
        synth_record = self._dispatch_and_wait(synth_id)
        task_states[synth_id] = synth_record["state"]
        synth_artifact = self._artifact(synth_id)
        if synth_record["state"] != "COMPLETED" or synth_artifact is None:
            return ProjectOutcome(project_id=project_id, status="human-wait",
                                  task_states=task_states,
                                  error="synth task failed or artifact missing")

        report_id = f"{project_id}-report"
        self._register_task(project_id, room_id, report_id, "argus-synth", "report",
                            "argus-report-materialize", snapshot,
                            synth_payload(run_id, snapshot, artifacts, decisions, policy),
                            required=True)
        report_record = self._dispatch_and_wait(report_id)
        task_states[report_id] = report_record["state"]

        return ProjectOutcome(
            project_id=project_id, status="completed",
            task_states=task_states,
            gate=synth_artifact.get("release_gate", "unknown"),
            report_paths=[f"tasks/{report_id}/result.md"])

    def _revision_loop(self, project_id: str, room_id: str,
                       task_states: dict, snapshot: SnapshotReference,
                       decisions: list[dict],
                       artifacts: list[dict]) -> ProjectOutcome | None:
        for _ in range(REVISION_LIMIT):
            revision_id = f"{project_id}-revision-{int(time.time())}"
            self._register_task(
                project_id, room_id, revision_id, "argus-meta", "revision",
                "argus-evidence-verify", snapshot,
                                meta_payload(project_id, snapshot, artifacts))
            record = self._dispatch_and_wait(revision_id)
            task_states[revision_id] = record["state"]
            if record["state"] != "COMPLETED":
                return ProjectOutcome(project_id=project_id, status="human-wait",
                                      task_states=task_states,
                                      error="revision task failed")
            revised = self._artifact(revision_id)
            if revised is None:
                return ProjectOutcome(project_id=project_id, status="human-wait",
                                      task_states=task_states,
                                      error="revision artifact missing")
            revised_decisions = revised.get("decisions", [])
            remaining = [d for d in revised_decisions if d.get("label") == "HALLUCINATION"]
            if not remaining:
                return None
        return ProjectOutcome(project_id=project_id, status="human-wait",
                              task_states=task_states,
                              error="revision limit exceeded; human review required")
