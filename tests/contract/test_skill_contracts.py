import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _skills():
    return sorted(p for p in (ROOT / "skills").iterdir()
                  if p.is_dir() and p.name.startswith("argus-"))


def test_each_skill_has_engineered_artifact_layout():
    assert _skills(), "no Argus skills found"
    for skill in _skills():
        assert (skill / "manifest.yaml").exists(), f"{skill.name} missing manifest"
        assert (skill / "SKILL.md").exists(), f"{skill.name} missing SKILL.md"
        assert (skill / "schemas/input.schema.json").exists(), f"{skill.name} missing input schema"
        assert (skill / "schemas/output.schema.json").exists(), f"{skill.name} missing output schema"
        assert (skill / "schemas/error.schema.json").exists(), f"{skill.name} missing error schema"
        assert (skill / "implementation/main.py").exists(), f"{skill.name} missing implementation"


def test_json_schemas_parse():
    for skill in _skills():
        for schema in (skill / "schemas").glob("*.json"):
            data = json.loads(schema.read_text(encoding="utf-8"))
            assert data["type"] == "object"
            assert data.get("additionalProperties") is False


def test_skill_docs_define_prohibitions():
    for skill in _skills():
        doc = (skill / "SKILL.md").read_text(encoding="utf-8")
        assert "禁止" in doc, f"{skill.name} missing prohibited conditions"
