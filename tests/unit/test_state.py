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


def test_version_monotonic_increment(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    assert store.get_version(rid) == 0
    store.transition(rid, "CREATED", "PREFLIGHT")
    assert store.get_version(rid) == 1
    store.transition(rid, "PREFLIGHT", "SNAPSHOTTING")
    assert store.get_version(rid) == 2
    store.save_run(rid, gate="block")
    assert store.get_version(rid) == 3


def test_written_by_recorded(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run(writer="manager-llm")
    store.transition(rid, "CREATED", "PREFLIGHT", writer="manager-llm")
    run = store.get_run(rid)
    assert run["written_by"] == "manager-llm"
    assert run["version"] == 1


def test_events_traceability(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run(writer="w1")
    store.transition(rid, "CREATED", "PREFLIGHT", writer="w1")
    store.save_run(rid, gate="warn", writer="w2")
    events = store.get_events(rid)
    assert [e["action"] for e in events] == ["create", "transition", "save"]
    assert [e["writer"] for e in events] == ["w1", "w1", "w2"]
    assert events[1]["from_status"] == "CREATED"
    assert events[1]["to_status"] == "PREFLIGHT"
    assert events[2]["version"] == 2
