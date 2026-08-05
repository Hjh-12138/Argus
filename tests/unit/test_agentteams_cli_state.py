"""AgentTeams audit must follow the shared run state machine.

Regression: the headless AgentTeams path used to transition
CREATED -> SNAPSHOTTING directly, which the state machine rejects. It must
go CREATED -> PREFLIGHT -> SNAPSHOTTING like the local path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.state import StateStore

import cli.argus as argus


class _FakeBundle:
    class _Snapshot:
        snapshot_id = "snap-1"
        files = [SimpleNamespace(path="app/main.py", sha256="0" * 64,
                                 size=5, language="python")]

    snapshot = _Snapshot()
    archive_sha256 = "archive-1"


class _FakeWorkspaceBuilder:
    def build(self, target, archive):
        return _FakeBundle()


class _FakeClient:
    pass


class _FakeDriver:
    last_snapshot = None

    def __init__(self, *args, **kwargs):
        self.calls = []

    def run(self, request, snapshot, profile="", acceptance_probe=None, **kwargs):
        from agentteams.project_driver import ProjectOutcome
        type(self).last_snapshot = snapshot
        return ProjectOutcome(project_id=request["project_id"], status="completed",
                              gate="block", report_paths=["tasks/p/report/result.md"],
                              task_states={})


def _run_agentteams_audit(tmp_path: Path) -> int:
    store = StateStore(tmp_path / "state.db")
    run_id = store.begin_run()
    target = tmp_path / "target"
    target.mkdir()
    (target / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    args = SimpleNamespace(target=str(target), headless=True, engine="agentteams",
                           block_on=None)
    cfg = argus.load_config([], Path.cwd())
    try:
        return argus._audit_agentteams(args, cfg, store, run_id, target)
    finally:
        store.close()


def test_agentteams_audit_uses_legal_state_prefix(tmp_path):
    with mock.patch("core.workspace_snapshot.WorkspaceSnapshotBuilder",
                    _FakeWorkspaceBuilder), \
         mock.patch("agentteams.hiclaw_client.HiclawClient", _FakeClient), \
         mock.patch("agentteams.project_driver.ProjectDriver", _FakeDriver):
        exit_code = _run_agentteams_audit(tmp_path)

    assert exit_code == 2  # block gate


def test_agentteams_audit_passes_built_archive_path(tmp_path):
    with mock.patch("core.workspace_snapshot.WorkspaceSnapshotBuilder",
                    _FakeWorkspaceBuilder), \
         mock.patch("agentteams.hiclaw_client.HiclawClient", _FakeClient), \
         mock.patch("agentteams.project_driver.ProjectDriver", _FakeDriver):
        _run_agentteams_audit(tmp_path)

    assert _FakeDriver.last_snapshot.archive_path.endswith(".zip")


def test_state_machine_rejects_created_to_snapshotting(tmp_path):
    store = StateStore(tmp_path / "state.db")
    run_id = store.begin_run()
    try:
        store.transition(run_id, "CREATED", "SNAPSHOTTING")
    except Exception as exc:  # noqa: BLE001
        from core.state import INVALID_TRANSITION
        assert isinstance(exc, INVALID_TRANSITION)
    else:
        raise AssertionError("CREATED -> SNAPSHOTTING must be rejected")
    finally:
        store.close()


def test_audit_agentteams_run_lands_completed(tmp_path):
    store = StateStore(tmp_path / "state.db")
    run_id = store.begin_run()
    target = tmp_path / "target"
    target.mkdir()
    args = SimpleNamespace(target=str(target), headless=True, engine="agentteams",
                           block_on=None)
    cfg = argus.load_config([], Path.cwd())
    try:
        with mock.patch("core.workspace_snapshot.WorkspaceSnapshotBuilder",
                        _FakeWorkspaceBuilder), \
             mock.patch("agentteams.hiclaw_client.HiclawClient", _FakeClient), \
             mock.patch("agentteams.project_driver.ProjectDriver", _FakeDriver):
            argus._audit_agentteams(args, cfg, store, run_id, target)
        assert store.get_status(run_id) == "COMPLETED"
    finally:
        store.close()
