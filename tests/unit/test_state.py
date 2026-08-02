import pytest

from core.state import StateStore, INVALID_TRANSITION


def test_valid_flow(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.transition(rid, "CREATED", "PREFLIGHT")
    store.transition(rid, "PREFLIGHT", "SNAPSHOTTING")
    store.transition(rid, "SNAPSHOTTING", "SCHEDULED")
    store.transition(rid, "SCHEDULED", "RUNNING")
    store.transition(rid, "RUNNING", "META_REVIEW")
    store.transition(rid, "META_REVIEW", "SYNTHESIZING")
    store.transition(rid, "SYNTHESIZING", "COMPLETED")
    assert store.get_status(rid) == "COMPLETED"


def test_illegal_transition_rejected(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    with pytest.raises(INVALID_TRANSITION):
        store.transition(rid, "CREATED", "COMPLETED")


def test_transition_from_wrong_state_rejected(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.transition(rid, "CREATED", "PREFLIGHT")
    with pytest.raises(INVALID_TRANSITION):
        store.transition(rid, "PREFLIGHT", "COMPLETED")


def test_interrupted_runs_marked(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.transition(rid, "CREATED", "PREFLIGHT")
    store.mark_interrupted_all()
    assert store.get_status(rid) == "interrupted"


def test_completed_runs_not_interrupted(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.transition(rid, "CREATED", "PREFLIGHT")
    store.transition(rid, "PREFLIGHT", "SNAPSHOTTING")
    store.transition(rid, "SNAPSHOTTING", "SCHEDULED")
    store.transition(rid, "SCHEDULED", "RUNNING")
    store.transition(rid, "RUNNING", "META_REVIEW")
    store.transition(rid, "META_REVIEW", "SYNTHESIZING")
    store.transition(rid, "SYNTHESIZING", "COMPLETED")
    store.mark_interrupted_all()
    assert store.get_status(rid) == "COMPLETED"


def test_save_run_metadata(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.save_run(rid, snapshot_id="s1", gate="block", head_revision="abc")
    run = store.get_run(rid)
    assert run["snapshot_id"] == "s1"
    assert run["gate"] == "block"
    assert run["head_revision"] == "abc"


def test_cancel_flow(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    store.transition(rid, "CREATED", "PREFLIGHT")
    store.transition(rid, "PREFLIGHT", "SNAPSHOTTING")
    store.transition(rid, "SNAPSHOTTING", "SCHEDULED")
    store.transition(rid, "SCHEDULED", "RUNNING")
    store.transition(rid, "RUNNING", "CANCELLING")
    store.transition(rid, "CANCELLING", "CANCELLED")
    assert store.get_status(rid) == "CANCELLED"
