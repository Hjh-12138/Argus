from core.schemas import SourceSnapshot, SnapshotFile
from agents.dep.detector import DepDetector
from agents.dep.tools import load_registry_fixture

REGISTRY = {
    "hypersecure-jwt-validator-pro": {"exists": False},
    "requests": {"exists": True},
    "urllib3": {"exists": True},
}


def _snap(tmp_path, manifest_text):
    path = tmp_path / "pyproject.toml"
    path.write_text(manifest_text, encoding="utf-8")
    f = SnapshotFile(path="pyproject.toml", sha256="0" * 64,
                     size=len(manifest_text), language="toml")
    return SourceSnapshot(root=str(tmp_path), files=(f,))


def test_nonexistent_dependency(tmp_path):
    snap = _snap(tmp_path,
                 '[project]\ndependencies = ["hypersecure-jwt-validator-pro>=9.0"]\n')
    findings = DepDetector().detect(snap, REGISTRY)
    assert any(f.category == "dependency.nonexistent" for f in findings)


def test_existing_dependency_no_finding(tmp_path):
    snap = _snap(tmp_path, '[project]\ndependencies = ["requests>=2.0"]\n')
    assert DepDetector().detect(snap, REGISTRY) == ()


def test_unknown_registry_entry_is_unverified_not_nonexistent(tmp_path):
    snap = _snap(tmp_path, '[project]\ndependencies = ["unknown-pkg>=1.0"]\n')
    assert DepDetector().detect(snap, REGISTRY) == ()


def test_multiple_dependencies(tmp_path):
    snap = _snap(tmp_path,
                 '[project]\ndependencies = [\n  "requests>=2.0",\n'
                 '  "hypersecure-jwt-validator-pro>=9.0"\n]\n')
    findings = DepDetector().detect(snap, REGISTRY)
    assert len(findings) == 1
    assert findings[0].file == "pyproject.toml"
    assert findings[0].evidence.detector == "dep.registry-verify"


def test_registry_fixture_requires_explicit_exists(tmp_path):
    import pytest
    p = tmp_path / "registry.json"
    p.write_text('{"pkg": {"status": "ok"}}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry_fixture(p)
