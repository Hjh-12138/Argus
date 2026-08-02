import pytest
from pathlib import Path

from core.config import load_config, ConfigValidationError


def test_unknown_field_rejected(tmp_path):
    (tmp_path / "argus.yaml").write_text("bogus_field: 1\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_config([], tmp_path)


def test_incomplete_run_enum(tmp_path):
    (tmp_path / "argus.yaml").write_text("policy:\n  incomplete_run: nonsense\n",
                                        encoding="utf-8")
    with pytest.raises(ConfigValidationError)


def test_cli_overrides_project(tmp_path):
    (tmp_path / "argus.yaml").write_text("policy:\n  block_on: [critical]\n",
                                        encoding="utf-8")
    cfg = load_config(["--block-on", "high"], tmp_path)
    assert cfg.policy.block_on == ["high"]


def test_defaults_when_no_config(tmp_path):
    cfg = load_config([], tmp_path)
    assert cfg.policy.block_on == ["critical", "high"]
    assert cfg.policy.min_confidence == 0.80
    assert cfg.policy.incomplete_run == "unknown"
    assert cfg.llm.send_source is False
    assert cfg.output.directory == ".argus/reports"


def test_env_overrides_project(tmp_path, monkeypatch):
    (tmp_path / "argus.yaml").write_text("llm:\n  base_url: http://local\n",
                                        encoding="utf-8")
    monkeypatch.setenv("ARGUS_LLM_BASE_URL", "http://env")
    cfg = load_config([], tmp_path)
    assert cfg.llm.base_url == "http://env"


def test_mcp_network_must_be_metadata_only(tmp_path):
    (tmp_path / "argus.yaml").write_text("mcp:\n  network: full\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError)


def test_effective_config_redacts_api_key(tmp_path):
    (tmp_path / "argus.yaml").write_text("llm:\n  api_key: sk-secret-12345\n",
                                        encoding="utf-8")
    cfg = load_config([], tmp_path)
    summary = str(cfg.__dict__)
    from core.config import effective_config_summary

    out = effective_config_summary(cfg)
    assert "sk-secret-12345" not in out
    assert "***" in out
