import pytest

from core.schemas import Finding, Evidence, SourceSnapshot, SnapshotFile


def _evidence(detector="test", sha="0" * 64) -> Evidence:
    return Evidence(context_lines=["x"], source_sha256=sha, redacted_value=None,
                    detector=detector, reasoning_summary=None)


def test_finding_requires_evidence_for_critical():
    with pytest.raises(ValueError):
        Finding(
            id="f1", agent="sec", category="security.sql_injection",
            severity="critical", confidence=0.95, title="t", detail="d",
            file=None, line_start=None, line_end=None, remediation="r",
            verification="v", rollback=None, cwe=None, fingerprint="fp",
            rule_id="R1", rule_version="1", evidence=None,
        )


def test_finding_rejects_absolute_path():
    with pytest.raises(ValueError):
        Finding(
            id="f2", agent="sec", category="security.sql_injection",
            severity="high", confidence=0.9, title="t", detail="d",
            file="/etc/passwd", line_start=1, line_end=1,
            remediation="r", verification="v", rollback=None, cwe=None,
            fingerprint="fp", rule_id="R1", rule_version="1",
            evidence=_evidence(),
        )


def test_finding_rejects_parent_traversal():
    with pytest.raises(ValueError):
        Finding(
            id="f3", agent="code", category="code.placeholder",
            severity="medium", confidence=0.8, title="t", detail="d",
            file="../secret.txt", line_start=1, line_end=1,
            remediation="r", verification="v", rollback=None, cwe=None,
            fingerprint="fp", rule_id="R1", rule_version="1",
            evidence=_evidence(),
        )


def test_finding_rejects_windows_drive():
    with pytest.raises(ValueError):
        Finding(
            id="f4", agent="sec", category="security.secret",
            severity="high", confidence=0.9, title="t", detail="d",
            file="C:\\secret\\config.py", line_start=1, line_end=1,
            remediation="r", verification="v", rollback=None, cwe=None,
            fingerprint="fp", rule_id="R1", rule_version="1",
            evidence=_evidence(),
        )


def test_relative_path_allowed():
    f = Finding(
        id="f5", agent="sec", category="security.secret",
        severity="high", confidence=0.9, title="t", detail="d",
        file="app/config.py", line_start=1, line_end=1,
        remediation="r", verification="v", rollback=None, cwe=None,
        fingerprint="fp", rule_id="R1", rule_version="1",
        evidence=_evidence(),
    )
    assert f.file == "app/config.py"


def test_snapshot_id_is_manifest_hash():
    a = SnapshotFile(path="a.py", sha256="1" * 64, size=3)
    b = SnapshotFile(path="b.py", sha256="2" * 64, size=4)
    s1 = SourceSnapshot(root="/p", files=(a, b))
    s2 = SourceSnapshot(root="/p", files=(b, a))  # 顺序无关
    assert s1.snapshot_id == s2.snapshot_id
    assert len(s1.snapshot_id) == 64


def test_agent_result_terminal():
    from core.schemas import AgentResult

    r = AgentResult(agent="sec", agent_version_id="v1", status="completed",
                    required=True, findings=(), input_snapshot_id="s",
                    rule_set_version="1", dataset_version="", metrics={})
    assert r.is_terminal
