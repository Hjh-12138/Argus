"""Simplest live audit: Manager posts the audit brief into a Project Room,
Workers collaborate conversationally, and the Synth worker writes the final
report to MinIO.  No typed-task protocol, no DAG polling — just Matrix chat
and shared storage.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.worker_payloads import ASSESSORS, CORE_AGENTS, SnapshotReference

PROJECT_WORKERS = [f"argus-{r}" for r in CORE_AGENTS]


@dataclass
class RoomOutcome:
    project_id: str
    room_id: str
    gate: str
    report_paths: list[str]
    status: str
    error: str = ""


class RoomDriver:
    """Create a Project Room, post the audit brief, and wait for the gate."""

    def __init__(self, client: HiclawClient, workspace: Path,
                 *, poll_interval_s: float = 30.0,
                   deadline_s: float = 600.0):
        self.client = client
        self.workspace = Path(workspace).resolve()
        self.poll_interval_s = poll_interval_s
        self.deadline_s = deadline_s

    # ── entry point ──────────────────────────────────────────────────────

    def run(self, target: Path, run_id: str | None = None,
            title: str = "", registry_fixture: Path | None = None,
            ) -> RoomOutcome:
        """Full end-to-end room audit."""
        project_id = f"argus-run-{run_id or uuid.uuid4().hex}"
        run_tag = f"run-{project_id.split('-run-', 1)[-1][:12]}"
        title = title or f"Argus audit {run_tag}"

        # 1 — snapshot
        archive = self.workspace / ".argus" / "snapshots" / f"{project_id}.zip"
        snapshot = self._build_snapshot(target, archive, project_id)

        # 2 — project room
        project = self.client.create_project(project_id, title, PROJECT_WORKERS)
        room_id = project.get("project_room_id")
        if not room_id:
            raise HiclawError("RoomDriver: no project room")

        # 3 — publish snapshot
        self._publish_snapshot(project_id, snapshot)

        # 4 — run the room in dependency order. Mentioning all six Workers at
        # once lets Meta/Synth finish before assessor artifacts exist.
        self._post_audit_brief(room_id, project_id, run_tag, snapshot, registry_fixture)
        self._wait_for_assessors(project_id)
        self._post_meta_stage(room_id, project_id)
        self._wait_for_meta(project_id)
        self._post_synth_stage(room_id, project_id)

        # 5 — wait for the Synth report on MinIO
        gate = self._wait_for_report(project_id)
        report_path = f"projects/{project_id}/report.json"

        return RoomOutcome(
            project_id=project_id, room_id=room_id,
            gate=gate, report_paths=[report_path],
            status="completed")

    # ── internals ─────────────────────────────────────────────────────────

    def _build_snapshot(self, target: Path, archive: Path,
                        project_id: str) -> SnapshotReference:
        from core.workspace_snapshot import WorkspaceSnapshotBuilder
        bundle = WorkspaceSnapshotBuilder().build(target, archive)
        return SnapshotReference(
            snapshot_id=bundle.snapshot.snapshot_id,
            source_root=f"/root/hiclaw-fs/shared/projects/{project_id}/snapshot",
            files=tuple({"path": f.path, "sha256": f.sha256, "size": f.size,
                         "language": f.language} for f in bundle.snapshot.files),
            archive_path=str(archive),
            archive_sha256=bundle.archive_sha256,
        )

    def _publish_snapshot(self, project_id: str, snapshot):
        import hashlib
        archive = Path(snapshot.archive_path)
        self.client.publish_shared_file(
            f"projects/{project_id}/snapshot.zip", archive)
        self.client.publish_shared_text(
            f"projects/{project_id}/snapshot.id",
            json.dumps({"snapshot_id": snapshot.snapshot_id,
                        "archive_sha256": snapshot.archive_sha256}),
        )

    def _post_audit_brief(self, room_id: str, project_id: str,
                          run_tag: str, snapshot,
                          registry_fixture: Path | None):
        """Send the natural-language audit brief into the Project Room."""
        # Build list of files for the brief
        file_summary = "\n".join(
            f"- `{f['path']}` ({f.get('language','?')}, {f['size']} bytes)"
            for f in snapshot.files[:20]
        ) if hasattr(snapshot, 'files') else "(see snapshot)"

        brief = (
            f"**🔍 New Audit — {run_tag}**\n\n"
            f"**Project**: `{project_id}`\n"
            f"**Snapshot**: `{snapshot.snapshot_id}`\n"
            f"**Archive**: `shared/projects/{project_id}/snapshot.zip`\n\n"
            f"## Target files\n{file_summary}\n\n"
            f"## Team — assessor stage\n\n"
            f"@argus-dep:matrix-local.agentteams.io:18080 — "
            f"Dependency audit: validate registry/manifest evidence\n\n"
            f"@argus-code:matrix-local.agentteams.io:18080 — "
            f"Code audit: correctness and state contracts\n\n"
            f"@argus-sec:matrix-local.agentteams.io:18080 — "
            f"Security audit: static security evidence\n\n"
            f"@argus-delivery:matrix-local.agentteams.io:18080 — "
            f"Delivery audit: CI and release evidence\n\n"
            f"## Constraints\n"
            f"- Read snapshot from the shared archive; do NOT modify target code\n"
            f"- Use your assigned Argus skills as analysis tools\n"
            f"- Post findings in this room and publish an artifact under "
            f"`shared/projects/{project_id}/`\n"
            f"- **When your assessor role is done, post `DONE`**"
        )
        assessors = [f"argus-{role}" for role in ASSESSORS]
        self.client.send_project_message(
            room_id, brief,
            [f"@{worker}:matrix-local.agentteams.io:18080" for worker in assessors])

    def _wait_for_any_artifacts(self, project_id: str, groups: list[tuple[str, ...]],
                                deadline_s: float | None = None) -> None:
        deadline = time.monotonic() + (deadline_s or self.deadline_s)
        while time.monotonic() < deadline:
            missing = [group for group in groups if not any(
                self.client.shared_exists(f"projects/{project_id}/{name}", refresh=True)
                for name in group)]
            if not missing:
                return
            time.sleep(self.poll_interval_s)
        names = ["|".join(group) for group in missing]
        raise HiclawError(f"project {project_id} missing stage artifacts: {names}")

    def _wait_for_assessors(self, project_id: str) -> None:
        self._wait_for_any_artifacts(project_id, [
            ("dep-findings.json", "findings-dep.md", "findings-argus-dep.md"),
            ("findings-code.md", "findings-argus-code.md", "code-findings.json"),
            ("findings-sec.md", "findings-argus-sec.md", "sec-findings.json"),
            ("findings-delivery.md", "delivery-findings.json"),
        ])

    def _post_meta_stage(self, room_id: str, project_id: str) -> None:
        body = (
            f"@argus-meta:matrix-local.agentteams.io:18080 META_STAGE `{project_id}`: "
            f"all assessor artifacts are now present under "
            f"`shared/projects/{project_id}/`. Verify evidence quality and publish "
            f"`meta-decisions.json` plus `meta-review.md`, then post `DONE`."
        )
        self.client.send_project_message(
            room_id, body, ["@argus-meta:matrix-local.agentteams.io:18080"])

    def _wait_for_meta(self, project_id: str) -> None:
        self._wait_for_any_artifacts(project_id, [("meta-decisions.json",)])

    def _post_synth_stage(self, room_id: str, project_id: str) -> None:
        body = (
            f"@argus-synth:matrix-local.agentteams.io:18080 SYNTH_STAGE `{project_id}`: "
            f"Meta review is ready at `shared/projects/{project_id}/meta-decisions.json`. "
            f"Read all assessor and Meta artifacts, then publish the final gate to "
            f"`shared/projects/{project_id}/report.json` and post `DONE`."
        )
        self.client.send_project_message(
            room_id, body, ["@argus-synth:matrix-local.agentteams.io:18080"])

    def _wait_for_report(self, project_id: str) -> str:
        """Poll MinIO for the synth report and fail if it never appears."""
        deadline = time.monotonic() + self.deadline_s
        report_path = f"projects/{project_id}/report.json"
        while time.monotonic() < deadline:
            try:
                text = self.client.read_shared_text(report_path, refresh=True)
                report = json.loads(text)
                gate = report.get("release_gate", "unknown")
                return gate
            except (HiclawError, json.JSONDecodeError):
                time.sleep(self.poll_interval_s)
        raise HiclawError(
            f"project {project_id} did not produce report.json before deadline")


# Keep the same interface the CLI used
def run_audit(target: Path, *, workspace: Path | None = None,
             registry_fixture: Path | None = None,
             run_id: str | None = None, title: str = "",
             ) -> RoomOutcome:
    """Convenience wrapper for calling RoomDriver from scripts."""
    ws = Path(workspace) if workspace else Path.cwd()
    client = HiclawClient()
    driver = RoomDriver(client, ws)
    return driver.run(target, run_id=run_id, title=title,
                      registry_fixture=registry_fixture)
