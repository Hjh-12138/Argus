import json
import os
import uuid
from pathlib import Path

import pytest

from agentteams.hiclaw_client import HiclawClient
from agentteams.orchestrator import CORE_AGENTS, WORKERS, Orchestrator


pytestmark = pytest.mark.agentteams
ROOT = Path(__file__).resolve().parents[2]
RUN_LIVE = os.environ.get("ARGUS_AGENTTEAMS_E2E") == "1"


@pytest.fixture(scope="module")
def hiclaw():
    return HiclawClient()


@pytest.fixture(scope="module")
def orchestrator(hiclaw):
    return Orchestrator(hiclaw, ROOT)


def test_workers_listable(hiclaw):
    workers = hiclaw.get_workers()
    assert isinstance(workers, list)


def test_six_core_workers_resident(hiclaw):
    workers = {w.get("name"): w for w in hiclaw.get_workers()}
    for agent in CORE_AGENTS:
        worker = WORKERS[agent]
        assert worker.name in workers, f"{worker.name} not registered"
        assert workers[worker.name].get("phase") in ("Ready", "Running")
        observed = hiclaw.get_worker_skill_observation(worker.name)
        ready = {skill.get("name") for skill in observed.get("skills", [])
                 if skill.get("ready")}
        assert ready == set(worker.skills)


def test_locked_skill_assignments_match_orchestrator():
    lock = json.loads((ROOT / "skills/skills.lock.json").read_text(encoding="utf-8"))
    expected = {worker.name: list(worker.skills) for worker in WORKERS.values()}
    assert lock["assignments"] == expected
    assert {s["name"] for s in lock["skills"]} == {
        skill for assigned in expected.values() for skill in assigned
    }


@pytest.mark.skipif(not RUN_LIVE, reason="set ARGUS_AGENTTEAMS_E2E=1 for live Project creation")
def test_project_room_task_dag_and_minio_artifacts(orchestrator, hiclaw):
    suffix = uuid.uuid4().hex[:8]
    project_id = f"argus-e2e-{suffix}"
    request = {
        "project_id": project_id,
        "title": f"Argus AgentTeams E2E {suffix}",
        "run_id": f"run-{suffix}",
        "snapshot_id": "a" * 64,
        "agents": ["dep", "code", "sec", "delivery"],
        "headless": True,
    }
    assert orchestrator.run_audit(request) == project_id

    project = json.loads(hiclaw.read_shared_text(f"projects/{project_id}/meta.json"))
    assert project["project_room_id"].startswith("!")
    assert project["status"] == "active"
    assert len(project["tasks"]) == 6

    assessor_ids = [f"{project_id}-assessor-{agent}"
                    for agent in ("dep", "code", "sec", "delivery")]
    for task_id in assessor_ids:
        meta = json.loads(hiclaw.read_shared_text(f"tasks/{task_id}/meta.json"))
        assert meta["status"] == "assigned"
        assert meta["depends_on"] == []
        assert hiclaw.shared_exists(f"tasks/{task_id}/spec.md", refresh=True)
        request_artifact = json.loads(
            hiclaw.read_shared_text(f"tasks/{task_id}/base/audit-request.json"))
        assert request_artifact["snapshot_id"] == "a" * 64
        assert "source" not in request_artifact

    meta_task = json.loads(
        hiclaw.read_shared_text(f"tasks/{project_id}-meta/meta.json"))
    synth_task = json.loads(
        hiclaw.read_shared_text(f"tasks/{project_id}-synth/meta.json"))
    assert meta_task["status"] == "pending"
    assert set(meta_task["depends_on"]) == set(assessor_ids)
    assert synth_task["status"] == "pending"
    assert synth_task["depends_on"] == [f"{project_id}-meta"]


def test_revision_needed_creates_revision_and_relocks_synth(monkeypatch, orchestrator):
    project_id = "argus-contract-revision"
    assessor = f"{project_id}-assessor-code"
    meta_id = f"{project_id}-meta"
    synth_id = f"{project_id}-synth"
    state = {
        f"projects/{project_id}/meta.json": {
            "project_id": project_id,
            "project_room_id": "!room:matrix",
            "status": "active",
            "tasks": [assessor, meta_id, synth_id],
        },
        f"tasks/{assessor}/meta.json": {
            "task_id": assessor, "kind": "assessor", "agent": "code",
            "assigned_to": "argus-code", "required": True,
        },
        f"tasks/{assessor}/base/audit-request.json": {
            "run_id": "r", "snapshot_id": "b" * 64, "agents": ["code"],
        },
        f"tasks/{meta_id}/meta.json": {
            "task_id": meta_id, "kind": "meta", "agent": "meta",
            "assigned_to": "argus-meta", "required": True,
        },
        f"tasks/{synth_id}/meta.json": {
            "task_id": synth_id, "kind": "synth", "agent": "synth",
            "assigned_to": "argus-synth", "required": True,
            "depends_on": [meta_id], "status": "pending",
        },
    }
    written = {}
    monkeypatch.setattr(orchestrator, "_read_json", lambda path: state[path])
    monkeypatch.setattr(orchestrator, "_write_json", lambda path, data: written.__setitem__(path, data))
    monkeypatch.setattr(orchestrator, "_write_task", lambda project, task, request: written.__setitem__(f"tasks/{task['task_id']}/meta.json", task))
    monkeypatch.setattr(orchestrator, "_append_revision_plan", lambda *args: None)
    monkeypatch.setattr(orchestrator.client, "sync_shared_directory", lambda *args: None)
    monkeypatch.setattr(orchestrator.client, "send_project_message", lambda *args: None)

    orchestrator._create_revision(state[f"projects/{project_id}/meta.json"],
                                  state[f"tasks/{meta_id}/meta.json"], assessor)

    revision_id = f"{assessor}-revision-1"
    recheck_id = f"{project_id}-meta-recheck-1"
    assert written[f"tasks/{revision_id}/meta.json"]["is_revision_for"] == assessor
    assert written[f"tasks/{recheck_id}/meta.json"]["depends_on"] == [revision_id]
    assert written[f"tasks/{synth_id}/meta.json"]["depends_on"] == [recheck_id]


def test_blocked_required_task_maps_to_human_wait(monkeypatch, orchestrator):
    project_id = "argus-contract-blocked"
    task_id = f"{project_id}-assessor-sec"
    project = {
        "project_id": project_id,
        "project_room_id": "!room:matrix",
        "status": "active",
        "tasks": [task_id],
    }
    task = {
        "task_id": task_id,
        "kind": "assessor",
        "agent": "sec",
        "assigned_to": "argus-sec",
        "required": True,
        "status": "assigned",
    }
    reads = {
        f"projects/{project_id}/meta.json": project,
        f"tasks/{task_id}/meta.json": task,
    }
    written = {}
    monkeypatch.setattr(orchestrator, "_read_json", lambda path: reads[path])
    monkeypatch.setattr(orchestrator, "_write_json", lambda path, data: written.__setitem__(path, data.copy()))
    monkeypatch.setattr(orchestrator, "_read_task_artifact", lambda meta: None)
    monkeypatch.setattr(orchestrator, "_mark_plan", lambda *args: None)
    monkeypatch.setattr(orchestrator.client, "pull_shared_directory", lambda *args: None)
    monkeypatch.setattr(orchestrator.client, "sync_shared_directory", lambda *args: None)
    monkeypatch.setattr(orchestrator.client, "send_project_message", lambda *args: None)
    monkeypatch.setattr(
        orchestrator.client, "read_shared_text",
        lambda path: "## Outcome\n\n**Status**: BLOCKED\n\n## Summary\n\nmissing authorization\n",
    )

    result = orchestrator.ingest_task_result(project_id, task_id)
    assert result.status == "BLOCKED"
    assert written[f"tasks/{task_id}/meta.json"]["status"] == "blocked"
    assert written[f"projects/{project_id}/meta.json"]["status"] == "human-wait"
