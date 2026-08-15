from core.policy import PolicyDecision
from core.reconcile import reconcile_report
from core.schemas import AgentResult, Evidence, Finding


def _finding(fid="f1", file="app.py", line_start=1, line_end=1,
             severity="medium"):
    return Finding(
        id=fid, agent="code", category="code.x", severity=severity,
        confidence=0.9, title="t", detail="d", file=file, line_start=line_start,
        line_end=line_end, remediation="fix", verification="rerun",
        fingerprint=f"fp-{fid}", rule_id="R", rule_version="1",
        evidence=Evidence(context_lines=("x",), source_sha256="0" * 64,
                          detector="code"),
    )


def _result(*findings):
    return AgentResult(
        agent="code", agent_version_id="code-v1", status="completed", required=True,
        findings=tuple(findings), input_snapshot_id="s", rule_set_version="1",
        dataset_version="", metrics={},
    )


def _report(gate="block", findings=(), summary=None):
    r = {"release_gate": gate, "findings": list(findings)}
    if summary is not None:
        r["summary"] = summary
    return r


def _item(fid, file="app.py", line_start=1, line_end=1, severity="medium"):
    return {"id": fid, "file": file, "line_start": line_start,
            "line_end": line_end, "severity": severity}


def _policy(gate="block"):
    return PolicyDecision(release_gate=gate, reasons=(), verified_finding_ids=(),
                          blocking_finding_ids=())


def test_clean_report_reconciles_clean():
    f = _finding()
    report = _report(gate="block", findings=[_item("f1")])
    rec = reconcile_report(report, [_result(f)], (), _policy("block"))
    assert not rec.gate_mismatch
    assert rec.unfounded_finding_ids == ()
    assert rec.inconsistent_finding_ids == ()
    assert rec.repaired_report["release_gate"] == "block"


def test_fabricated_finding_removed():
    f = _finding()
    report = _report(gate="block", findings=[_item("f1"), _item("ghost", file="x.py")])
    rec = reconcile_report(report, [_result(f)], (), _policy("block"))
    assert rec.unfounded_finding_ids == ("ghost",)
    kept_ids = [x["id"] for x in rec.repaired_report["findings"]]
    assert "ghost" not in kept_ids
    assert kept_ids == ["f1"]


def test_tampered_finding_flagged_kept():
    f = _finding(severity="medium")
    # 报告把 severity 篡改成 critical
    report = _report(gate="block", findings=[_item("f1", severity="critical")])
    rec = reconcile_report(report, [_result(f)], (), _policy("block"))
    assert rec.inconsistent_finding_ids == ("f1",)
    kept = rec.repaired_report["findings"][0]
    assert kept["id"] == "f1"
    assert kept["reconciliation_status"] == "INCONSISTENT"


def test_gate_mismatch_recomputed_from_shared_state():
    f = _finding()
    # 报告谎称 pass，但共享状态重算 gate=block
    report = _report(gate="pass", findings=[_item("f1")])
    rec = reconcile_report(report, [_result(f)], (), _policy("block"))
    assert rec.gate_mismatch
    assert rec.recomputed_gate == "block"
    assert rec.repaired_report["release_gate"] == "block"


def test_summary_isolated_not_trusted():
    f = _finding()
    report = _report(gate="block", findings=[_item("f1")],
                     summary="LLM free-text summary")
    rec = reconcile_report(report, [_result(f)], (), _policy("block"))
    assert rec.summary_flagged
    assert rec.repaired_report["reconciliation"]["summary_isolated"] is True
