import hashlib

from core.meta import MetaReviewer
from core.schemas import AgentResult, Evidence, Finding, SnapshotFile, SourceSnapshot


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _snapshot(tmp_path, rel="app.py", content="x=1\n"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    written = path.read_bytes()
    sf = SnapshotFile(path=rel, sha256=hashlib.sha256(written).hexdigest(),
                      size=len(written), language="py")
    return SourceSnapshot(root=str(tmp_path), files=(sf,)), sf


def _finding(sf, **overrides):
    data = dict(
        id="f1", agent="code", category="code.placeholder", severity="medium",
        confidence=0.9, title="t", detail="d", file=sf.path,
        line_start=1, line_end=1, remediation="fix it", verification="rerun",
        rollback=None, cwe=None, fingerprint="fp", rule_id="R", rule_version="1",
        evidence=Evidence(context_lines=("x",), source_sha256=sf.sha256,
                          redacted_value=None, detector="code", reasoning_summary=None),
    )
    data.update(overrides)
    return Finding(**data)


def _result(snapshot, *findings):
    return AgentResult(
        agent="code", agent_version_id="code-v1", status="completed", required=True,
        findings=tuple(findings), input_snapshot_id=snapshot.snapshot_id,
        rule_set_version="1", prompt_version=None, model_version=None,
        dataset_version="", error_code=None, error_message=None, metrics={},
    )


def test_hallucinated_path_rejected(tmp_path):
    snap, sf = _snapshot(tmp_path)
    fake = _finding(sf, file="app/config.py", line_start=88, line_end=88)
    decisions = MetaReviewer().review(snap, [_result(snap, fake)])
    assert decisions[0].label == "HALLUCINATION"
    assert "PATH_NOT_IN_SNAPSHOT" in decisions[0].reason_codes


def test_valid_finding_verified(tmp_path):
    snap, sf = _snapshot(tmp_path, content="x=1\n")
    decisions = MetaReviewer().review(snap, [_result(snap, _finding(sf))])
    assert decisions[0].label == "VERIFIED"
    assert decisions[0].checked_source_sha256 == sf.sha256


def test_out_of_range_line_is_hallucination(tmp_path):
    snap, sf = _snapshot(tmp_path, content="x=1\n")
    f = _finding(sf, line_start=10, line_end=10)
    d = MetaReviewer().review(snap, [_result(snap, f)])[0]
    assert d.label == "HALLUCINATION"
    assert "LINE_OUT_OF_RANGE" in d.reason_codes


def test_hash_mismatch_is_hallucination(tmp_path):
    snap, sf = _snapshot(tmp_path)
    ev = Evidence(context_lines=("x",), source_sha256="f" * 64,
                  redacted_value=None, detector="code", reasoning_summary=None)
    f = _finding(sf, evidence=ev)
    d = MetaReviewer().review(snap, [_result(snap, f)])[0]
    assert d.label == "HALLUCINATION"
    assert "EVIDENCE_HASH_MISMATCH" in d.reason_codes


def test_source_changed_after_snapshot_needs_evidence(tmp_path):
    snap, sf = _snapshot(tmp_path, content="x=1\n")
    (tmp_path / "app.py").write_text("x=2\n", encoding="utf-8")
    d = MetaReviewer().review(snap, [_result(snap, _finding(sf))])[0]
    assert d.label == "NEEDS_EVIDENCE"
    assert "SNAPSHOT_HASH_MISMATCH" in d.reason_codes


def test_missing_remediation_not_actionable(tmp_path):
    snap, sf = _snapshot(tmp_path)
    f = _finding(sf, remediation="")
    d = MetaReviewer().review(snap, [_result(snap, f)])[0]
    assert d.label == "NOT_ACTIONABLE"
