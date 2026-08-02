import pytest
from pathlib import Path

from core.preflight import preflight


def test_preflight_rejects_nonexistent(tmp_path):
    with pytest.raises(SystemExit) as e:
        preflight(tmp_path / "nope", None)
    assert e.value.code == 4


def test_preflight_detects_symlink_escape(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    (target / "evil").symlink_to(outside)
    r = preflight(target, None)
    assert r.ok
    assert any("evil" in u for u in r.unsafe_links)


def test_preflight_language_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    r = preflight(tmp_path, None)
    assert r.language == "python"
    assert r.manifest is True
