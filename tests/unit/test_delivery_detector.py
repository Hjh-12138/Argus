from agents.delivery.detector import DeliveryDetector
from core.schemas import SnapshotFile, SourceSnapshot


def _snap(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append(SnapshotFile(path=rel, sha256="0" * 64, size=len(content)))
    return SourceSnapshot(root=str(tmp_path), files=tuple(snaps))


def test_ci_only_compiles_but_tests_exist(tmp_path):
    snap = _snap(tmp_path, {
        ".github/workflows/ci.yml": "steps:\n  - run: python -m compileall .\n",
        "tests/test_app.py": "def test_x(): pass\n",
    })
    findings = DeliveryDetector().detect(snap)
    assert any(f.category == "delivery.test_gap" for f in findings)


def test_ci_runs_tests_no_gap(tmp_path):
    snap = _snap(tmp_path, {
        ".github/workflows/ci.yml": "steps:\n  - run: pytest\n",
        "tests/test_app.py": "def test_x(): pass\n",
    })
    assert DeliveryDetector().detect(snap) == ()


def test_no_test_files_no_gap(tmp_path):
    snap = _snap(tmp_path, {
        ".github/workflows/ci.yml": "steps:\n  - run: python -m compileall .\n",
    })
    assert DeliveryDetector().detect(snap) == ()
