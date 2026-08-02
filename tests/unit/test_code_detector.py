from agents.code.detector import CodeDetector
from core.schemas import SnapshotFile, SourceSnapshot


def _snap(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append(SnapshotFile(path=rel, sha256="0" * 64, size=len(content)))
    return SourceSnapshot(root=str(tmp_path), files=tuple(snaps))


def test_placeholder_detected(tmp_path):
    snap = _snap(tmp_path, {"app/foo.py":
        "def handler():\n    return 'TODO: implement'\n"})
    findings = CodeDetector().detect(snap)
    assert any(f.category == "code.placeholder" for f in findings)


def test_real_implementation_no_finding(tmp_path):
    snap = _snap(tmp_path, {"app/foo.py":
        "def handler():\n    return {'status': 'ok'}\n"})
    assert CodeDetector().detect(snap) == ()


def test_placeholder_evidence_has_source_hash(tmp_path):
    snap = _snap(tmp_path, {"app/foo.py":
        "def handler():\n    raise NotImplementedError\n"})
    finding = CodeDetector().detect(snap)[0]
    assert finding.evidence.source_sha256 == "0" * 64
    assert finding.file == "app/foo.py"
    assert finding.line_start == 2
