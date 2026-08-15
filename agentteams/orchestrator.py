"""Manager-Agent-driven audits for Argus.

The Manager Agent is an LLM coordinator: Argus only builds and publishes the
snapshot, submits a natural-language audit brief over the admin DM, and waits
for the Manager to publish the final gate report to MinIO. The Manager creates
the Project Room, coordinates the six Workers conversationally, and decides
when synthesis is complete. No local DAG, no typed-task registration.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agentteams.hiclaw_client import HiclawClient, HiclawError


ASSESSORS = ("dep", "code", "sec", "delivery")
REPORT_POLL_S = 30.0
REPORT_DEADLINE_S = 2400.0


class ManagerError(HiclawError):
    pass


def submit_managed_audit(target: Path, run_id: str, *, workspace: Path | None = None,
                         agents: tuple[str, ...] = ASSESSORS,
                         title: str = "",
                         registry_fixture: Path | None = None,
                         demo_invalid: bool = False,
                         cfg=None) -> dict:
    """Build and publish the snapshot, submit the brief to the Manager, wait."""
    from core.workspace_snapshot import WorkspaceSnapshotBuilder

    ws = Path(workspace) if workspace else Path.cwd()
    client = HiclawClient()
    project_id = f"argus-run-{run_id}"

    archive = ws / ".argus" / "snapshots" / f"{project_id}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    bundle = WorkspaceSnapshotBuilder().build(target, archive)
    client.publish_shared_file(f"projects/{project_id}/snapshot.zip", archive)
    client.publish_shared_text(
        f"projects/{project_id}/snapshot.id",
        json.dumps({"snapshot_id": bundle.snapshot.snapshot_id,
                    "archive_sha256": bundle.archive_sha256}, ensure_ascii=False))
    if registry_fixture is not None and Path(registry_fixture).is_file():
        client.publish_shared_file(
            f"projects/{project_id}/registry-fixture.json", Path(registry_fixture))

    manager = _manager_record(client)
    admin_room = _admin_dm_room(client, manager)
    matrix_domain = _manager_matrix_domain(manager)
    workers = [f"argus-{agent}" for agent in agents]
    scope_lines = "\n".join(
        f"- @{name}:{matrix_domain}" for name in workers)
    notes = []
    if registry_fixture is not None and Path(registry_fixture).is_file():
        notes.append(
            "The dependency assessor must read the registry evidence at "
            "`shared/projects/{project_id}/registry-fixture.json` when validating "
            "manifest entries.")
    if demo_invalid:
        notes.append(
            "This target contains one intentionally invalid finding marker; "
            "evaluate it honestly and report it as a finding.")
    notes_block = "\n".join(f"- {note}" for note in notes)

    brief = (
        f"@manager **New Argus Audit**\n\n"
        f"Run ID: `{run_id}`\n"
        f"Project ID: `{project_id}`\n"
        f"Title: {title or f'Argus audit {run_id}'}\n\n"
        f"## Target\n"
        f"Snapshot archive: `shared/projects/{project_id}/snapshot.zip`\n"
        f"Snapshot ID: `{bundle.snapshot.snapshot_id}`\n\n"
        f"## Scope\n"
        f"Audit these domains and coordinate the assigned Workers "
        f"conversationally in a Project Room you create:\n"
        f"{scope_lines}\n\n"
        f"## Notes\n{notes_block}\n\n"
        f"## Deliverable\n"
        f"When the Workers have produced and you are satisfied with the "
        f"evidence, synthesize the release gate and write the final report to "
        f"`shared/projects/{project_id}/report.json` with a `release_gate` of "
        f"`pass`, `warn`, `block`, or `unknown`, a `findings` list, and a "
        f"`summary`. Then notify me here.\n"
        f"Decide the gate yourself from the collected evidence; do not wait "
        f"for further instructions."
    )
    # The Manager only routes messages that mention it (bindings=0 otherwise),
    # so the brief must carry an explicit @manager mention to be processed.
    client.send_admin_dm(admin_room, brief,
                         mentions=[f"@manager:{matrix_domain}"])
    report = wait_for_report(client, project_id)
    # R4.1 对账：读回共享状态重算 gate，不信任 LLM 自述的 gate。
    llm_gate = report.get("release_gate")
    if cfg is None:
        from core.config import load_config
        cfg = load_config([], Path.cwd())
    from agentteams.reconcile_managed import reconcile_managed_report
    report = reconcile_managed_report(client, project_id, report, cfg)
    recon = report.get("reconciliation", {})
    recon["llm_gate"] = llm_gate
    report["reconciliation"] = recon
    # Consumers (cli.argus._audit_agentteams) read a flat dict with "gate" and
    # "project_id" on top of the report fields.
    return {"gate": report["release_gate"], "project_id": project_id, **report}


def wait_for_report(client: HiclawClient, project_id: str,
                    *, timeout_s: float = REPORT_DEADLINE_S) -> dict:
    """Wait for the Manager-published report on MinIO and validate its gate."""
    deadline = time.monotonic() + timeout_s
    path = f"projects/{project_id}/report.json"
    while time.monotonic() < deadline:
        try:
            text = client.read_shared_text(path, refresh=True)
            report = json.loads(text)
        except (HiclawError, json.JSONDecodeError):
            time.sleep(REPORT_POLL_S)
            continue
        if not isinstance(report, dict):
            raise ManagerError(f"{path} is not a JSON object")
        gate = report.get("release_gate")
        if gate not in ("pass", "warn", "block", "unknown"):
            raise ManagerError(f"{path} has invalid release_gate: {gate!r}")
        return report
    raise ManagerError(
        f"project {project_id} did not produce report.json within "
        f"{int(timeout_s)}s")


def _manager_record(client: HiclawClient) -> dict:
    raw = client._docker_exec_in(
        "agentteams-controller", "hiclaw", "get", "managers", "default",
        "-o", "json")
    try:
        manager = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManagerError("Manager resource returned invalid JSON") from exc
    if not isinstance(manager, dict):
        raise ManagerError("Manager resource returned unexpected JSON")
    return manager


def _manager_matrix_domain(manager: dict) -> str:
    matrix_user = manager.get("matrixUserID")
    if not isinstance(matrix_user, str) or ":" not in matrix_user:
        raise ManagerError("Manager Matrix identity is not ready")
    return matrix_user.split(":", 1)[1]


def _admin_dm_room(client: HiclawClient, manager: dict | None = None) -> str:
    current = manager or _manager_record(client)
    room = current.get("roomID")
    if isinstance(room, str) and room:
        return room

    state = json.loads(client._docker_exec(
        "cat", "/root/manager-workspace/state.json"))
    room = state.get("admin_dm_room_id")
    if not room:
        raise ManagerError(
            "Manager admin DM room not found. Run Manager onboarding first.")
    return room


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
