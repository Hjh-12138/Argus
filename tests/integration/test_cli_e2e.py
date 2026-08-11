import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "demo/scenarios/ai-pr-three-defects"
REGISTRY = SCENARIO / "registry-fixture.json"


def _audit(target: Path, workdir: Path, demo_invalid=False):
    cmd = [
        sys.executable, "-m", "cli.argus", "audit",
        "--target", str(target), "--headless", "--engine", "local",
        "--registry-fixture", str(REGISTRY),
    ]
    if demo_invalid:
        cmd.append("--demo-invalid-finding")
    return subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                          timeout=120, env={**__import__("os").environ,
                                            "PYTHONPATH": str(ROOT)})


def test_vulnerable_target_blocks_with_three_real_findings(tmp_path):
    result = _audit(SCENARIO / "vulnerable", tmp_path, demo_invalid=True)
    assert result.returncode == 2, (
        f"expected block, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
    data = json.loads((tmp_path / ".argus/reports/report.json").read_text(encoding="utf-8"))
    assert data["release_gate"] == "block"
    categories = {f["category"] for f in data["findings"]}
    assert {"security.sql_injection", "dependency.nonexistent", "delivery.test_gap"} <= categories
    assert data["summary"]["meta_quality"]["hallucination"] == 1
    assert "demo-hallucination-config-88" not in {f["id"] for f in data["findings"]}


def test_fixed_target_passes(tmp_path):
    result = _audit(SCENARIO / "fixed", tmp_path)
    assert result.returncode == 0, (
        f"expected pass, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
    data = json.loads((tmp_path / ".argus/reports/report.json").read_text(encoding="utf-8"))
    assert data["release_gate"] == "pass"
    assert data["summary"]["blocking_findings"] == 0


def test_report_snapshot_ids_differ(tmp_path):
    vuln_dir = tmp_path / "vuln-run"; vuln_dir.mkdir()
    fixed_dir = tmp_path / "fixed-run"; fixed_dir.mkdir()
    _audit(SCENARIO / "vulnerable", vuln_dir)
    _audit(SCENARIO / "fixed", fixed_dir)
    v = json.loads((vuln_dir / ".argus/reports/report.json").read_text(encoding="utf-8"))
    f = json.loads((fixed_dir / ".argus/reports/report.json").read_text(encoding="utf-8"))
    assert v["target"]["snapshot_id"] != f["target"]["snapshot_id"]
