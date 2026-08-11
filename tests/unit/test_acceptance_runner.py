"""Acceptance runner decision logic: exit-code contract, gate checks,
suite-count parsing, canary scan, and doc verification."""
from __future__ import annotations

import json
from pathlib import Path

from acceptance import phase_one as pn
from acceptance.evidence import EvidenceCollector


def _evidence(tmp_path: Path) -> EvidenceCollector:
    return EvidenceCollector(tmp_path)


def test_audit_completed_boundaries():
    for code in (0, 1, 2, 3):
        assert pn._audit_completed(code)
    for code in (-1, 4, 130):
        assert not pn._audit_completed(code)


def test_pytest_summary_parses_counts():
    clean = pn._pytest_summary("144 passed, 6 deselected in 2.84s")
    assert clean["passed"] == 144
    assert clean["deselected"] == 6
    assert clean["failed"] == 0
    failure = pn._pytest_summary("1 failed, 5 passed, 2 skipped, 144 deselected in 24s")
    assert failure["failed"] == 1
    assert failure["passed"] == 5
    assert failure["skipped"] == 2
    assert pn._pytest_summary("")["passed"] == 0


def test_a1_passes_when_block_and_all_categories(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    report = {
        "release_gate": "block",
        "findings": [
            {"category": "dependency.nonexistent"},
            {"category": "security.sql_injection"},
            {"category": "delivery.test_gap"},
        ],
    }
    monkeypatch.setattr(pn, "_read_agentteams_report", lambda stdout: report)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 2, "stdout": "status=completed"})
    assert pn._a1_agentteams(ev, True).status == "PASS"


def test_a1_fails_when_missing_category(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    report = {"release_gate": "block",
              "findings": [{"category": "dependency.nonexistent"}]}
    monkeypatch.setattr(pn, "_read_agentteams_report", lambda stdout: report)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 2, "stdout": "status=completed"})
    item = pn._a1_agentteams(ev, True)
    assert item.status == "FAIL"
    assert "delivery.test_gap" in item.detail


def test_a1_fails_when_gate_is_not_block(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 0, "stdout": "status=completed"})
    assert pn._a1_agentteams(ev, True).status == "FAIL"


def test_agentteams_completed_marker():
    assert pn._agentteams_completed(
        "[argus] project=p status=completed gate=block")
    assert not pn._agentteams_completed("Traceback ... task did not reach terminal")


def test_a2_requires_block_on_agentteams_demo(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 2, "stdout": "status=completed"})
    assert pn._a2_agentteams_demo(ev, True).status == "PASS"
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 0, "stdout": "status=completed"})
    item = pn._a2_agentteams_demo(ev, True)
    assert item.status == "FAIL"
    assert "block" in item.detail


def test_a2_fails_when_crash_without_completion_marker(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 1, "stdout": "Traceback ..."})
    item = pn._a2_agentteams_demo(ev, True)
    assert item.status == "FAIL"
    assert "did not complete" in item.detail


def test_a3_passes_when_fixed_and_clean(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    report = {"release_gate": "pass",
              "findings": [{"category": "security.other"}]}
    monkeypatch.setattr(pn, "_read_agentteams_report", lambda stdout: report)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 0, "stdout": "status=completed"})
    assert pn._a3_agentteams(ev, True).status == "PASS"


def test_a3_fails_when_vulnerable_category_remains(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    report = {"release_gate": "pass",
              "findings": [{"category": "security.sql_injection"}]}
    monkeypatch.setattr(pn, "_read_agentteams_report", lambda stdout: report)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 0, "stdout": "status=completed"})
    assert pn._a3_agentteams(ev, True).status == "FAIL"


def test_a5_locked_eight_skills_and_six_assignments(tmp_path):
    ev = _evidence(tmp_path)
    item = pn._a5_skill_lock(ev, False)
    assert item.status == "PASS"
    assert "8" in item.detail


def test_a6_records_suite_counts(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)

    def fake_run(name, argv, **kw):
        if name == "A6-local-suite":
            return {"exit": 0, "stdout": "144 passed, 6 deselected in 2s\n"}
        return {"exit": 0, "stdout": "6 passed, 144 deselected in 13s\n"}

    monkeypatch.setattr(ev, "run_command", fake_run)
    item = pn._a6_suites(ev, True)
    assert item.status == "PASS"
    assert "144 passed" in item.detail


def test_scan_canary_detects_only_real_hits(tmp_path):
    needle = "ARGUS_CANARY_abc"
    hit = tmp_path / "hit.txt"
    clean = tmp_path / "clean.txt"
    hit.write_text(f"secret {needle} here", encoding="utf-8")
    clean.write_text("no canary", encoding="utf-8")
    hits = pn._scan_canary(needle, {"surface": [hit, clean]})
    assert len(hits) == 1
    assert str(hit) in hits[0]


def test_a7_leakage_passes_when_no_hits(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(ev, "run_command",
                        lambda *a, **k: {"exit": 0, "stdout": "clean", "stderr": ""})
    monkeypatch.setattr(pn, "_scan_canary", lambda *a, **k: [])
    item = pn._a7_leakage(ev, tmp_path / "run", True)
    assert item.status == "PASS"


def test_a8_fails_when_intro_exceeds_500(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(pn, "INTRO_PATH", tmp_path / "intro.md")
    monkeypatch.setattr(pn, "PPT_PATH", tmp_path / "ppt.md")
    monkeypatch.setattr(pn, "ACCEPTANCE_MD", tmp_path / "acceptance.md")
    (tmp_path / "intro.md").write_text("x" * 600, encoding="utf-8")
    (tmp_path / "ppt.md").write_text("# PPT\n", encoding="utf-8")
    (tmp_path / "acceptance.md").write_text("run-123", encoding="utf-8")
    item = pn._a8_docs(ev, "run-123")
    assert item.status == "FAIL"
    assert "600 字" in item.detail


def test_a8_passes_when_docs_meet_contract(tmp_path, monkeypatch):
    ev = _evidence(tmp_path)
    monkeypatch.setattr(pn, "INTRO_PATH", tmp_path / "intro.md")
    monkeypatch.setattr(pn, "PPT_PATH", tmp_path / "ppt.md")
    monkeypatch.setattr(pn, "ACCEPTANCE_MD", tmp_path / "acceptance.md")
    (tmp_path / "intro.md").write_text("y" * 300, encoding="utf-8")
    (tmp_path / "ppt.md").write_text("# PPT\n", encoding="utf-8")
    (tmp_path / "acceptance.md").write_text("run-456", encoding="utf-8")
    # README + skills.lock.json checks read the real repo artifacts.
    item = pn._a8_docs(ev, "run-456")
    assert item.status == "PASS"
