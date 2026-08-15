import json

from agentteams.hiclaw_client import HiclawError
from agentteams.reconcile_managed import (
    decision_from_dict, extract_decisions, extract_findings, finding_from_dict,
    reconcile_managed_report,
)
from core.config import Config


class FakeClient:
    def __init__(self, files: dict[str, str]):
        self.files = files
        self.calls: list[str] = []

    def read_shared_text(self, path, refresh=False):
        self.calls.append(path)
        if path not in self.files:
            raise HiclawError(f"missing {path}")
        return self.files[path]


def _finding_dict(fid="f1", severity="critical", file="app/search.py",
                  confidence=0.95):
    return {
        "id": fid, "agent": "sec", "category": "security.sql_injection",
        "severity": severity, "confidence": confidence, "title": "t", "detail": "d",
        "file": file, "line_start": 1, "line_end": 1, "fingerprint": f"fp-{fid}",
        "rule_id": "R", "rule_version": "1", "remediation": "fix",
        "verification": "rerun", "rollback": None, "cwe": None,
        "evidence": {"detector": "sec", "source_sha256": "0" * 64, "redacted": False},
    }


def _decision_dict(fid="f1", label="VERIFIED"):
    return {"finding_id": fid, "label": label, "reason_codes": ["OK"],
            "detail": "ok", "checked_source_sha256": "0" * 64}


def _report(gate="pass", findings=()):
    return {"release_gate": gate, "findings": list(findings)}


def test_extract_findings_tolerates_formats():
    f = _finding_dict()
    assert extract_findings([f]) == [f]                      # list of bare
    assert extract_findings([{"finding": f}]) == [f]         # list of wrappers
    assert extract_findings({"findings": [f]}) == [f]        # wrapper dict
    assert extract_findings("not a list") == []


def test_extract_decisions_tolerates_formats():
    d = _decision_dict()
    assert extract_decisions({"decisions": [d]}) == [d]
    assert extract_decisions([d]) == [d]


def test_finding_from_dict_reconstructs_host_type():
    f = finding_from_dict(_finding_dict())
    assert f is not None
    assert f.id == "f1" and f.severity == "critical" and f.file == "app/search.py"


def test_finding_from_dict_rejects_malformed():
    bad = _finding_dict(severity="critical", file=None)
    assert finding_from_dict(bad) is None


def test_decision_from_dict_reconstructs():
    d = decision_from_dict(_decision_dict(label="HALLUCINATION"))
    assert d.finding_id == "f1" and d.label == "HALLUCINATION"


def test_reconcile_recomputes_gate_and_flags_mismatch():
    files = {
        "projects/p1/dep-findings.json": "[]",
        "projects/p1/code-findings.json": "[]",
        "projects/p1/sec-findings.json": json.dumps([_finding_dict()]),
        "projects/p1/delivery-findings.json": "[]",
        "projects/p1/meta-decisions.json": json.dumps({"decisions": [_decision_dict()]}),
    }
    client = FakeClient(files)
    report = _report(gate="pass", findings=[_finding_dict()])  # LLM 谎称 pass
    repaired = reconcile_managed_report(client, "p1", report, Config())

    assert repaired["release_gate"] == "block"  # 从共享状态重算
    recon = repaired["reconciliation"]
    assert recon["gate_mismatch"] is True
    assert recon["recomputed_gate"] == "block"
    assert recon["unfounded_finding_ids"] == []
    assert recon["inconsistent_finding_ids"] == []


def test_reconcile_removes_fabricated_finding():
    files = {
        "projects/p1/dep-findings.json": "[]",
        "projects/p1/code-findings.json": "[]",
        "projects/p1/sec-findings.json": json.dumps([_finding_dict()]),
        "projects/p1/delivery-findings.json": "[]",
        "projects/p1/meta-decisions.json": json.dumps({"decisions": [_decision_dict()]}),
    }
    client = FakeClient(files)
    # 报告里多一个无来源的 ghost finding（编造）
    report = _report(gate="block", findings=[
        _finding_dict(), _finding_dict(fid="ghost", file="x.py")])
    repaired = reconcile_managed_report(client, "p1", report, Config())
    assert repaired["reconciliation"]["unfounded_finding_ids"] == ["ghost"]
    assert "ghost" not in [f["id"] for f in repaired["findings"]]


def test_reconcile_missing_artifacts_is_fail_closed():
    client = FakeClient({})  # 全部产物缺失
    report = _report(gate="pass", findings=[])
    repaired = reconcile_managed_report(client, "p1", report, Config())
    # 机器产物缺失 → 无法核验 → 绝不信任 LLM 的 pass
    assert repaired["release_gate"] == "unknown"
