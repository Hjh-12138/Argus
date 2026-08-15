import hashlib

from core.schemas import AgentResult, Evidence, Finding, SnapshotFile, SourceSnapshot
from core.verify import verify_agent_result


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


def test_valid_finding_passes_boundary(tmp_path):
    snap, sf = _snapshot(tmp_path)
    v = verify_agent_result(snap, _result(snap, _finding(sf)))
    assert v.passed
    assert v.hallucinated_finding_ids == ()
    assert v.clean_findings == _result(snap, _finding(sf)).findings


def test_hallucinated_finding_intercepted(tmp_path):
    snap, sf = _snapshot(tmp_path)
    fake = _finding(sf, file="app/config.py", line_start=88, line_end=88)
    good = _finding(sf)
    v = verify_agent_result(snap, _result(snap, fake, good))
    assert not v.passed
    assert v.hallucinated_finding_ids == ("f1",)
    assert "PATH_NOT_IN_SNAPSHOT" in v.reason_codes
    # 幻觉被剔除，只保留合法 finding。
    assert [f.id for f in v.clean_findings] == ["f1"]


def test_mixed_findings_keep_good_only(tmp_path):
    snap, sf = _snapshot(tmp_path)
    fake = _finding(sf, id="bad", file="nope.py")
    good = _finding(sf, id="ok")
    v = verify_agent_result(snap, _result(snap, fake, good))
    assert v.hallucinated_finding_ids == ("bad",)
    assert [f.id for f in v.clean_findings] == ["ok"]
