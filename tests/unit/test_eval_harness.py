"""R5.1 评测 harness 纯逻辑单元测试（不跑 subprocess，手工喂 report dict）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "demo" / "eval"))

from harness import _sample_tokens, _token_capture, evaluate_reports, semantic_key


def _finding(agent="sec", category="security.secret", file_="app/auth.py",
             line=1, title="Hardcoded credential", id_="det-1"):
    return {"id": id_, "agent": agent, "category": category, "file": file_,
            "line_start": line, "line_end": line, "severity": "critical",
            "title": title}


def _gt(expected_gate="block", findings=()):
    return {"schema_version": "1", "scenario_id": "t", "category": "simple",
            "expected_gate": expected_gate, "expected_findings": list(findings)}


def _run(gate="block", findings=()):
    return {"ok": True,
            "report": {"release_gate": gate, "findings": list(findings)},
            "exit_code": 0}


# --- semantic_key -----------------------------------------------------------

def test_semantic_key_uses_agent_category_file_line():
    key = semantic_key(_finding())
    assert key == ("sec", "security.secret", "app/auth.py", 1)


def test_semantic_key_ignores_detector_id_and_fingerprint():
    a = _finding(id_="det-1", line=3)
    b = _finding(id_="det-999", line=3)
    a["fingerprint"] = "f-1"
    b["fingerprint"] = "f-2"
    assert semantic_key(a) == semantic_key(b)


def test_semantic_key_missing_line_is_none():
    f = _finding()
    f["line_start"] = None
    assert semantic_key(f)[3] is None


# --- evaluate_reports: 召回 -------------------------------------------------

def test_recall_full_match():
    gt = _gt(findings=[_finding()])
    runs = [_run(findings=[_finding()])]
    r = evaluate_reports(runs, gt)
    assert r["recall"] == 1.0
    assert r["precision"] == 1.0
    assert r["gate_consistent"] is True
    assert r["full_match"] is True
    assert r["missing_gt_keys"] == []
    assert r["false_positive_keys"] == []


def test_recall_miss_reports_missing_key():
    gt = _gt(findings=[_finding(id_="k1", file_="a.py"),
                       _finding(id_="k2", file_="b.py")])
    runs = [_run(findings=[_finding(id_="k1", file_="a.py")])]
    r = evaluate_reports(runs, gt)
    assert r["recall"] == 0.5
    assert len(r["missing_gt_keys"]) == 1
    assert r["missing_gt_keys"][0][2] == "b.py"


def test_false_positive_lowers_precision():
    gt = _gt(findings=[_finding(id_="k1", file_="a.py")])
    runs = [_run(findings=[_finding(id_="k1", file_="a.py"),
                           _finding(id_="k2", file_="zz.py")])]
    r = evaluate_reports(runs, gt)
    assert r["precision"] == 0.5
    assert len(r["false_positive_keys"]) == 1


def test_cross_run_dedup_no_double_precision_penalty():
    gt = _gt(findings=[_finding(id_="k1", file_="a.py")])
    runs = [_run(findings=[_finding(id_="k1", file_="a.py"),
                           _finding(id_="fp", file_="zz.py")]),
            _run(findings=[_finding(id_="k1", file_="a.py"),
                           _finding(id_="fp", file_="zz.py")])]
    r = evaluate_reports(runs, gt)
    # 同一 FP 在两次 run 重复报，去重后仍只算 1 个 FP。
    assert len(r["false_positive_keys"]) == 1
    assert r["precision"] == 0.5
    assert r["recall"] == 1.0


# --- evaluate_reports: gate 一致性 -----------------------------------------

def test_gate_consistent_when_all_runs_match():
    gt = _gt(expected_gate="block", findings=[_finding()])
    runs = [_run(gate="block"), _run(gate="block")]
    r = evaluate_reports(runs, gt)
    assert r["gate_consistent"] is True
    assert r["gate_distribution"] == {"block": 2}


def test_gate_mismatch_reported():
    gt = _gt(expected_gate="pass", findings=[])
    runs = [_run(gate="block"), _run(gate="block")]
    r = evaluate_reports(runs, gt)
    assert r["gate_consistent"] is False
    assert r["gate_distribution"] == {"block": 2}


def test_error_run_is_fail_closed_not_pass():
    gt = _gt(findings=[_finding()])
    runs = [_run(findings=[_finding()]),
            {"ok": False, "error": "report.json not written",
             "stdout": "", "stderr": ""}]
    r = evaluate_reports(runs, gt)
    assert r["errors"] == ["report.json not written"]
    assert r["gate_consistent"] is False
    assert r["full_match"] is False


# --- evaluate_reports: 空 ground truth（纯精确测试）-------------------------

def test_empty_gt_and_no_findings_is_vacuous_pass():
    gt = _gt(expected_gate="pass", findings=[])
    r = evaluate_reports([_run(gate="pass")], gt)
    assert r["recall"] == 1.0
    assert r["precision"] == 1.0
    assert r["full_match"] is True


def test_empty_gt_with_fp_fails_precision():
    gt = _gt(expected_gate="pass", findings=[])
    r = evaluate_reports([_run(gate="pass", findings=[_finding()])], gt)
    assert r["precision"] == 0.0
    assert len(r["false_positive_keys"]) == 1
    assert r["full_match"] is False


def test_nonempty_gt_all_runs_error_recall_zero():
    gt = _gt(findings=[_finding()])
    runs = [{"ok": False, "error": "boom", "stdout": "", "stderr": ""}]
    r = evaluate_reports(runs, gt)
    assert r["recall"] == 0.0
    assert r["gate_consistent"] is False


# --- token 成本捕获（agentteams 差分） ---

class _StubCaptor:
    def __init__(self, value=None, error=False):
        self.value = value
        self.error = error

    def __call__(self):
        if self.error:
            raise RuntimeError("gateway down")
        return self.value


def test_sample_tokens_disabled_returns_none():
    assert _sample_tokens(None) == (None, None)


def test_sample_tokens_ok():
    value, err = _sample_tokens(_StubCaptor(42))
    assert value == 42 and err is None


def test_sample_tokens_error_recorded_not_raised():
    value, err = _sample_tokens(_StubCaptor(error=True))
    assert value is None and "gateway down" in err


def test_token_capture_computes_deltas():
    import types
    before = types.SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120)
    after = types.SimpleNamespace(input_tokens=150, output_tokens=30, total_tokens=180)
    assert _token_capture(before, after) == {
        "input_delta": 50, "output_delta": 10, "total_delta": 60,
    }
