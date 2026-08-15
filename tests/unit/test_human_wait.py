import pytest

from agentteams.protocol import TaskState, parse_record
from core.state import INVALID_TRANSITION, StateStore


def _running_run(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    for f, t in (("CREATED", "PREFLIGHT"), ("PREFLIGHT", "SNAPSHOTTING"),
                 ("SNAPSHOTTING", "SCHEDULED"), ("SCHEDULED", "RUNNING")):
        store.transition(rid, f, t)
    return store, rid


def test_protocol_accepts_human_wait():
    rec = parse_record({"task_id": "task-a", "state": "HUMAN_WAIT",
                        "revision": 1, "assigned_worker": "argus-sec",
                        "attempt": 1, "required": True})
    assert rec.state == TaskState.HUMAN_WAIT
    # 非终态：还在等人工
    assert TaskState.HUMAN_WAIT not in __import__(
        "agentteams.protocol", fromlist=["TERMINAL_STATES"]).TERMINAL_STATES


def test_wait_for_human_pauses_run(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    assert store.get_status(rid) == "HUMAN_WAIT"


def test_resume_retry_returns_to_running(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    target = store.resume(rid, "retry")
    assert target == "RUNNING"
    assert store.get_status(rid) == "RUNNING"


def test_resume_skip_degraded_to_partial(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    target = store.resume(rid, "skip")
    assert target == "PARTIAL"
    assert store.get_status(rid) == "PARTIAL"


def test_resume_unknown_is_fail_closed(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    store.resume(rid, "unknown")
    assert store.get_status(rid) == "PARTIAL"
    assert store.get_run(rid)["gate"] == "unknown"


def test_resume_abort_fails_run(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    store.resume(rid, "abort")
    assert store.get_status(rid) == "FAILED"


def test_resume_retry_from_meta_review(tmp_path):
    store = StateStore(tmp_path / "state.db")
    rid = store.begin_run()
    for f, t in (("CREATED", "PREFLIGHT"), ("PREFLIGHT", "SNAPSHOTTING"),
                 ("SNAPSHOTTING", "SCHEDULED"), ("SCHEDULED", "RUNNING"),
                 ("RUNNING", "META_REVIEW")):
        store.transition(rid, f, t)
    store.wait_for_human(rid)
    assert store.resume(rid, "retry") == "META_REVIEW"


def test_invalid_decision_rejected(tmp_path):
    store, rid = _running_run(tmp_path)
    store.wait_for_human(rid)
    with pytest.raises(ValueError):
        store.resume(rid, "pass")


def test_cannot_wait_from_terminal(tmp_path):
    store, rid = _running_run(tmp_path)
    store.transition(rid, "RUNNING", "PARTIAL")
    with pytest.raises(INVALID_TRANSITION):
        store.wait_for_human(rid)
