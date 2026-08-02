from core.config import Config
from core.meta import MetaDecision
from core.policy import evaluate_policy
from core.schemas import AgentResult, Evidence, Finding


def _result(fid: str, severity: str, *, status="completed", required=True,
            confidence=0.99) -> AgentResult:
    finding = Finding(
        id=fid, agent="sec", category="security.secret", severity=severity,
        confidence=confidence, title="t", detail="d", file="app.py",
        line_start=1, line_end=1, remediation="r", verification="v",
        rollback=None, cwe="CWE-798", fingerprint=fid,
        rule_id="SEC-002", rule_version="1",
        evidence=Evidence(context_lines=("x",), source_sha256="0" * 64,
                          redacted_value="h", detector="sec", reasoning_summary=None),
    )
    return AgentResult(
        agent="sec", agent_version_id="sec-v1", status=status,
        required=required, findings=(finding,), input_snapshot_id="s",
        rule_set_version="1", prompt_version=None, model_version=None,
        dataset_version="", error_code=None, error_message=None, metrics={},
    )


def test_verified_critical_blocks():
    decision = MetaDecision("f1", "VERIFIED", ("OK",), "ok")
    policy = evaluate_policy([decision], [_result("f1", "critical")], Config(),
                             expected_required={"sec"})
    assert policy.release_gate == "block"
    assert policy.blocking_finding_ids == ("f1",)


def test_hallucination_does_not_block():
    decision = MetaDecision("f1", "HALLUCINATION", ("PATH_NOT_IN_SNAPSHOT",), "no")
    policy = evaluate_policy([decision], [_result("f1", "critical")], Config(),
                             expected_required={"sec"})
    assert policy.release_gate == "pass"


def test_required_missing_yields_unknown():
    policy = evaluate_policy([], [], Config(), expected_required={"sec"})
    assert policy.release_gate == "unknown"


def test_required_failed_yields_unknown():
    result = _result("f1", "critical", status="failed")
    policy = evaluate_policy([], [result], Config(), expected_required={"sec"})
    assert policy.release_gate == "unknown"


def test_medium_warns():
    decision = MetaDecision("f1", "VERIFIED", ("OK",), "ok")
    policy = evaluate_policy([decision], [_result("f1", "medium")], Config(),
                             expected_required={"sec"})
    assert policy.release_gate == "warn"


def test_low_confidence_does_not_block():
    decision = MetaDecision("f1", "VERIFIED", ("OK",), "ok")
    policy = evaluate_policy([decision],
                             [_result("f1", "critical", confidence=0.2)], Config(),
                             expected_required={"sec"})
    assert policy.release_gate == "pass"
