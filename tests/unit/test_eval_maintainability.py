import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GT = (ROOT / "demo/eval/simple/simple-maintainability/ground-truth.json")
SRC = (ROOT / "demo/eval/simple/simple-maintainability/src/app/pricing.py")


def test_ground_truth_line_numbers_match_fixture():
    gt = json.loads(GT.read_text(encoding="utf-8"))
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()
    for exp in gt["expected_findings"]:
        lo = exp["line_start"] - 1
        assert 0 <= lo < len(lines), exp["key"]
        # 每个 ground-truth finding 的行必须有可辨别的信号
        assert lines[lo].strip(), exp["key"]


def test_fixture_does_not_trigger_heuristic_rules():
    import sys
    sys.path.insert(0, str(ROOT / "skills/argus-code-maintainability-scan/implementation"))
    from rules import scan_path
    text = SRC.read_text(encoding="utf-8")
    rules = {h.rule_id for h in scan_path("app/pricing.py", text)}
    assert {"CODE-101", "CODE-104", "CODE-105", "CODE-107", "CODE-108"} <= rules
    assert not rules & {"CODE-102", "CODE-103", "CODE-106", "CODE-109", "CODE-110", "CODE-111"}
