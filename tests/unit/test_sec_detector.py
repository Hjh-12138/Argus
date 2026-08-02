from agents.sec.detector import SecDetector
from core.schemas import SnapshotFile, SourceSnapshot, finding_to_dict


def _snap(tmp_path, files: dict[str, str]) -> SourceSnapshot:
    snaps = []
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        snaps.append(SnapshotFile(path=rel, sha256="0" * 64,
                                  size=len(content), language=path.suffix.lstrip(".")))
    return SourceSnapshot(root=str(tmp_path), files=tuple(snaps))


def test_sql_injection_found(tmp_path):
    snap = _snap(tmp_path, {"app/search.py":
        "query = 'SELECT * FROM users WHERE id = ' + user_input\n"})
    findings = SecDetector().detect(snap)
    assert any(f.category == "security.sql_injection" and f.severity == "critical"
               for f in findings)


def test_parameterized_sql_no_finding(tmp_path):
    snap = _snap(tmp_path, {"app/search.py":
        "db.execute('SELECT * FROM users WHERE id = %s', (user_id,))\n"})
    assert not any(f.category == "security.sql_injection"
                   for f in SecDetector().detect(snap))


def test_hardcoded_secret_redacted_in_finding(tmp_path):
    raw = "sk-super-secret-1234567890"
    snap = _snap(tmp_path, {"app/config.py": f"API_KEY = '{raw}'\n"})
    findings = SecDetector().detect(snap)
    sec = [f for f in findings if f.category == "security.secret"]
    assert sec
    rendered = str(finding_to_dict(sec[0]))
    assert raw not in sec[0].detail
    assert raw not in rendered
    assert sec[0].evidence.redacted_value
    assert len(sec[0].evidence.redacted_value) == 64


def test_placeholder_secret_ignored(tmp_path):
    snap = _snap(tmp_path, {"app/config.py": "API_KEY = 'your-api-key-placeholder'\n"})
    assert not any(f.category == "security.secret" for f in SecDetector().detect(snap))


def test_non_source_file_ignored(tmp_path):
    snap = _snap(tmp_path, {"notes.txt":
        "query = 'SELECT * FROM users WHERE id = ' + user_input\n"})
    assert SecDetector().detect(snap) == ()
