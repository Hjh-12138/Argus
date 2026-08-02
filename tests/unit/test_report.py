import hashlib
import json

from core.config import Config
from core.meta import MetaDecision
from core.policy import evaluate_policy
from core.report import render_report, write_report
from core.schemas import AgentResult, Evidence, Finding, SnapshotFile, SourceSnapshot


def _fixture(tmp_path):
    content = "x=1\n"
    (tmp_path / "app.py").write_text(content, encoding="utf-8")
    sha = hashlib.sha256(content.encode()).hexdigest()
    sf = SnapshotFile(path="app.py", sha256=sha, size=len(content), language="py")
    snapshot = SourceSnapshot(root=str(tmp_path), files=(sf,))
    finding = Finding(
        id="f1", agent="code", category="code.placeholder", severity="medium",
        confidence=0.9, title="placeholder", detail="d", file="app.py",
        line_start=1, line_end=1, remediation="implement", verification="rerun",
        rollback=None, cwe=None, fingerprint="fp", rule_id="CODE-001",
        rule_version="1", evidence=Evidence(
            context_lines=("x=1",), source_sha256=sha, redacted_value=None,
            detector="code", reasoning_summary=None),
    )
    result = AgentResult(
        agent="code", agent_version_id="code-v1", status="completed", required=True,
        findings=(finding,), input_snapshot_id=snapshot.snapshot_id,
        rule_set_version="1", dataset_version="", metrics={},
    )
    decision = MetaDecision("f1", "VERIFIED", ("OK",), "ok", sha)
    policy = evaluate_policy([decision], [result], Config(), expected_required={"code"})
    return snapshot, result, decision, policy


def test_report_json_schema_v2(tmp_path):
    snapshot, result, decision, policy = _fixture(tmp_path)
    data = render_report("r1", snapshot, (result,), (decision,), policy)
    assert data["schema_version"] == "2.0"
    assert data["release_gate"] == "warn"
    assert data["run_status"] == "completed"
    assert data["attack_verdict"] == "NOT_RUN"
    assert data["target"]["source_path"] == "<local-redacted>"
    json.dumps(data)


def test_report_writes_json_and_markdown_atomically(tmp_path):
    snapshot, result, decision, policy = _fixture(tmp_path)
    data = render_report("r1", snapshot, (result,), (decision,), policy)
    out = tmp_path / "reports"
    json_path, md_path = write_report(out, data)
    assert json_path.exists() and md_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["run_id"] == "r1"
    assert "Release Gate: warn" in md_path.read_text(encoding="utf-8")
    assert not list(out.glob("*.tmp"))


def test_hallucination_excluded_from_main_findings(tmp_path):
    snapshot, result, _, _ = _fixture(tmp_path)
    decision = MetaDecision("f1", "HALLUCINATION", ("PATH_NOT_IN_SNAPSHOT",), "no")
    policy = evaluate_policy([decision], [result], Config(), expected_required={"code"})
    data = render_report("r1", snapshot, (result,), (decision,), policy)
    assert data["findings"] == []
    assert data["summary"]["meta_quality"]["hallucination"] == 1
