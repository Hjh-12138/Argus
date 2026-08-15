"""R5.2 评测门禁纯逻辑单元测试（不跑 subprocess / 不跑评测）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "demo" / "eval"))

from gate import (DEFAULT_WEIGHTS, compare, eval_fingerprint,
                  engine_fingerprint, gate_score, load_pin, total_cost,
                  write_pin)


def _scenario(sid, recall=1.0, precision=1.0, gate_consistent=True,
              full_match=True, expected_gate="block", tokens=None):
    return {
        "scenario_id": sid, "title": sid, "category": "simple",
        "expected_gate": expected_gate, "runs": 1, "errors": [],
        "gate_distribution": {expected_gate: 1},
        "gate_consistent": gate_consistent, "full_match": full_match,
        "argus_findings": [], "matched_gt_keys": [], "missing_gt_keys": [],
        "false_positive_keys": [], "recall": recall, "precision": precision,
        "f1": 0.0, "tokens": tokens,
    }


def _report(scenarios, with_audit_errors=0):
    n = len(scenarios)
    full = sum(1 for s in scenarios if s["full_match"])
    gate_ok = sum(1 for s in scenarios if s["gate_consistent"])
    recall_macro = sum(s["recall"] for s in scenarios) / n if n else 1.0
    precision_macro = sum(s["precision"] for s in scenarios) / n if n else 1.0
    return {
        "schema_version": "1", "argv": [],
        "summary": {
            "scenarios": n, "full_match": full, "gate_consistent": gate_ok,
            "with_audit_errors": with_audit_errors,
            "recall_macro": recall_macro, "precision_macro": precision_macro,
        },
        "scenarios": scenarios,
    }


# --- gate_score -------------------------------------------------------------

def test_gate_score_default_weights_are_unweighted_sum():
    r = _report([_scenario("a"), _scenario("a2")])
    # recall 1.0 + precision 1.0 + gate_ratio 1.0
    assert gate_score(r) == 3.0


def test_gate_score_honors_custom_weights():
    r = _report([_scenario("a"), _scenario("a2")])
    assert gate_score(r, {"recall": 2.0, "precision": 1.0, "gate": 1.0}) == 4.0


# --- compare: 通过 ----------------------------------------------------------

def test_compare_identical_is_accepted():
    base = _report([_scenario("a"), _scenario("b")])
    verdict = compare(base, _report([_scenario("a"), _scenario("b")]))
    assert verdict.accepted is True
    assert verdict.failures == []
    assert any("no regression" in n for n in verdict.notes)


def test_compare_known_gap_stays_gap_is_accepted():
    # 基线本身是 DIFF（gate 不一致），当前仍 DIFF：不新变坏，接受。
    base = _report([_scenario("a", gate_consistent=False, full_match=False,
                              recall=0.8, expected_gate="unknown")])
    cur = _report([_scenario("a", gate_consistent=False, full_match=False,
                             recall=0.8, expected_gate="unknown")])
    verdict = compare(base, cur)
    assert verdict.accepted is True


# --- compare: 回归拒绝 ------------------------------------------------------

def test_recall_regression_rejected():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a", recall=0.5, full_match=False)])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("a: recall 0.50 < baseline 1.00" in f for f in verdict.failures)


def test_precision_regression_rejected():
    base = _report([_scenario("a", precision=1.0)])
    cur = _report([_scenario("a", precision=0.5, full_match=False)])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("precision" in f for f in verdict.failures)


def test_gate_consistency_loss_rejected():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a", gate_consistent=False, full_match=False,
                             expected_gate="pass")])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("gate consistency lost" in f for f in verdict.failures)


def test_audit_errors_fail_closed():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a")], with_audit_errors=1)
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("audit errors" in f for f in verdict.failures)


# --- compare: 覆盖变化 ------------------------------------------------------

def test_new_scenario_full_match_accepted_with_note():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a"), _scenario("b")])
    verdict = compare(base, cur)
    assert verdict.accepted is True
    assert any("new scenario 'b' full_match" in n for n in verdict.notes)


def test_new_scenario_not_full_match_rejected():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a"),
                   _scenario("b", recall=0.0, full_match=False)])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("new scenario 'b' not full_match" in f for f in verdict.failures)


def test_coverage_regression_rejected():
    base = _report([_scenario("a"), _scenario("b")])
    cur = _report([_scenario("a")])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("coverage regression" in f for f in verdict.failures)


def test_weighted_score_drop_is_failure():
    base = _report([_scenario("a", recall=1.0)])
    cur = _report([_scenario("a", recall=0.5, full_match=False)])
    verdict = compare(base, cur)
    assert verdict.accepted is False
    assert any("weighted score" in f for f in verdict.failures)


def test_custom_weights_do_not_break_compare():
    base = _report([_scenario("a")])
    cur = _report([_scenario("a")])
    verdict = compare(base, cur, weights={"recall": 2.0, "precision": 0.5, "gate": 1.0})
    assert verdict.accepted is True
    assert verdict.weights["recall"] == 2.0


# --- pin 读写 ---------------------------------------------------------------

def test_pin_write_then_load_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proj = root / "proj"
        ev = root / "eval"
        for d in ("core", "agents", "cli", "agentteams"):
            (proj / d).mkdir(parents=True)
        ev.mkdir(parents=True)
        report = _report([_scenario("a")])
        pin_path = root / "eval.lock.json"
        write_pin(pin_path, report, dict(DEFAULT_WEIGHTS),
                  project_root=proj, eval_root=ev)
        loaded = load_pin(pin_path)
        assert loaded["baseline"]["summary"]["scenarios"] == 1
        assert loaded["argus_version"] == "unknown"  # 非 git 临时目录
        assert loaded["eval_fingerprint"].startswith("sha256:")
        assert loaded["engine_fingerprint"].startswith("sha256:")


def test_load_pin_rejects_without_baseline():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bad.json"
        p.write_text('{"schema_version":"1"}', encoding="utf-8")
        import pytest
        with pytest.raises(ValueError):
            load_pin(p)


# --- 指纹 -------------------------------------------------------------------

def _write(tree: Path, rel: str, data: bytes = b"x"):
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_engine_fingerprint_deterministic_and_ignores_pycache():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "core/a.py", b"def f(): return 1\n")
        _write(root, "core/__pycache__/a.pyc", b"\x00pyc")
        _write(root, "agents/b.py", b"def g(): return 2\n")
        fp1 = engine_fingerprint(root)
        # 增加 pyc 不影响指纹
        _write(root, "cli/__pycache__/x.pyc", b"\x00pyc2")
        assert engine_fingerprint(root) == fp1
        # 改源码则指纹变化
        _write(root, "core/a.py", b"def f(): return 99\n")
        assert engine_fingerprint(root) != fp1


def test_eval_fingerprint_ignores_dot_dirs():
    """dot 目录里的 ground-truth 副本（stray copy）不应算入测量基准。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "manifest.json", b'{"scenarios": []}')
        _write(root, "simple/s-clean/ground-truth.json", b'{"a": 1}')
        fp1 = eval_fingerprint(root)
        # dot 目录里的副本，改了也不影响指纹
        _write(root, ".eval-copy/simple/s-clean/ground-truth.json", b'{"a": 99}')
        assert eval_fingerprint(root) == fp1


def test_eval_fingerprint_tracks_ground_truth_and_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "manifest.json", b'{"scenarios": []}')
        _write(root, "simple/s-clean/ground-truth.json", b'{"a": 1}')
        fp1 = eval_fingerprint(root)
        # 新增 ground truth 变指纹
        _write(root, "simple/s-extra/ground-truth.json", b'{"b": 2}')
        assert eval_fingerprint(root) != fp1
        # 修改既有 ground truth 变指纹
        _write(root, "simple/s-clean/ground-truth.json", b'{"a": 99}')
        assert eval_fingerprint(root) != fp1


# --- token 成本（D3 成本维度） ---

def _tok(total):
    return {"total_delta": total, "input_delta": int(total * 0.9),
            "output_delta": int(total * 0.1)}


def test_total_cost_sums_deltas():
    report = _report([_scenario("a", tokens=_tok(1000)),
                      _scenario("b", tokens=_tok(500))])
    assert total_cost(report) == 1500


def test_total_cost_none_when_any_scenario_missing_tokens():
    assert total_cost(_report([_scenario("a")])) is None
    assert total_cost(_report([_scenario("a", tokens=_tok(1)),
                               _scenario("b")])) is None


def test_cost_within_budget_accepted():
    base = _report([_scenario("a", tokens=_tok(1000))])
    cur = _report([_scenario("a", tokens=_tok(1100))])
    verdict = compare(base, cur, max_cost_ratio=1.2)
    assert verdict.accepted is True
    assert verdict.cost_base == 1000
    assert verdict.cost_cur == 1100


def test_cost_regression_rejected():
    base = _report([_scenario("a", tokens=_tok(1000))])
    cur = _report([_scenario("a", tokens=_tok(1500))])
    verdict = compare(base, cur, max_cost_ratio=1.2)  # 1500 > 1000*1.2
    assert verdict.accepted is False
    assert any("token cost 1,500 > baseline 1,000" in f for f in verdict.failures)


def test_cost_gate_missing_token_data_fail_closed():
    base = _report([_scenario("a")])  # 无 token 数据
    cur = _report([_scenario("a")])
    verdict = compare(base, cur, max_cost_ratio=1.2)
    assert verdict.accepted is False
    assert any("token data missing" in f for f in verdict.failures)


def test_cost_ignored_without_ratio_but_noted():
    base = _report([_scenario("a", tokens=_tok(1000))])
    cur = _report([_scenario("a", tokens=_tok(5000))])
    verdict = compare(base, cur)  # 无 max_cost_ratio
    assert verdict.accepted is True
    assert any("token cost baseline=1,000 current=5,000" in n for n in verdict.notes)


def test_cost_introduced_from_zero_rejected():
    base = _report([_scenario("a", tokens=_tok(0))])
    cur = _report([_scenario("a", tokens=_tok(500))])
    verdict = compare(base, cur, max_cost_ratio=1.0)  # 500 > 0*1.0
    assert verdict.accepted is False
    assert any("token cost" in f for f in verdict.failures)
