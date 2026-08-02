from core.snapshot import SnapshotBuilder


def test_snapshot_fingerprints_are_stable(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    s1, c1 = SnapshotBuilder().build(tmp_path)
    (tmp_path / "b.txt").write_text("noise", encoding="utf-8")
    s2, c2 = SnapshotBuilder().build(tmp_path)

    f1 = {f.path: f.sha256 for f in s1.files}
    f2 = {f.path: f.sha256 for f in s2.files}
    assert f1["a.py"] == f2["a.py"]
    assert c1.files_total < c2.files_total


def test_snapshot_skips_binary_and_oversize(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    big = tmp_path / "big.bin"
    big.write_bytes(b"0" * (6 * 1024 * 1024))
    snap, cov = SnapshotBuilder().build(tmp_path)
    paths = {f.path for f in snap.files}
    assert "a.py" in paths
    assert "img.png" not in paths
    assert "big.bin" not in paths
    assert cov.skip_reasons.get("binary", 0) >= 1
    assert cov.skip_reasons.get("oversize", 0) >= 1


def test_snapshot_paths_are_posix_relative(tmp_path):
    (tmp_path / "sub" / "a.py").write_text("x=1\n", encoding="utf-8")
    snap, _ = SnapshotBuilder().build(tmp_path)
    for f in snap.files:
        assert not f.path.startswith("/")
        assert "\\" not in f.path


def test_snapshot_id_changes_when_content_changes(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    s1, _ = SnapshotBuilder().build(tmp_path)
    (tmp_path / "a.py").write_text("x=2\n", encoding="utf-8")
    s2, _ = SnapshotBuilder().build(tmp_path)
    assert s1.snapshot_id != s2.snapshot_id
