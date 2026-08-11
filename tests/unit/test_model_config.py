from pathlib import Path

import pytest

from agentteams.model_config import (
    PLACEHOLDER_MODELS,
    SUPPORTED_MODELS,
    load_locked_model,
    model_mismatch,
    validate_model,
)


def test_supported_models_are_explicit():
    assert SUPPORTED_MODELS == frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})


@pytest.mark.parametrize("value", sorted(PLACEHOLDER_MODELS | {"   ", "gpt-unknown"}))
def test_invalid_models_are_rejected(value):
    with pytest.raises(ValueError):
        validate_model(value)


@pytest.mark.parametrize("value", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_supported_model_is_normalized(value):
    assert validate_model(f"  {value} ") == value


def test_lock_loader_requires_valid_model(tmp_path: Path):
    lock = tmp_path / "contract.lock.json"
    lock.write_text('{"model":"model"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_locked_model(lock)


def test_model_mismatch_is_sanitized():
    text = model_mismatch("argus-code", "deepseek-v4-flash", "model")
    assert text == (
        "worker=argus-code expected_model=deepseek-v4-flash "
        "effective_model=model"
    )
    assert "token" not in text.lower()
    assert "password" not in text.lower()
