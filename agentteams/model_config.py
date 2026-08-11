"""Validated model policy for live AgentTeams Worker configuration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
PLACEHOLDER_MODELS = frozenset(
    {"", "model", "default", "placeholder", "test", "unknown"}
)


def validate_model(model: str) -> str:
    """Return a supported model name or reject unsafe placeholders."""
    if not isinstance(model, str):
        raise ValueError("Worker model must be a string")
    normalized = model.strip()
    if normalized.lower() in PLACEHOLDER_MODELS:
        raise ValueError(f"invalid Worker model placeholder: {normalized!r}")
    if normalized not in SUPPORTED_MODELS:
        raise ValueError(f"unsupported Worker model: {normalized!r}")
    return normalized


def load_locked_model(lock_path: Path) -> str:
    """Load and validate the model from the immutable contract lock."""
    try:
        data = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read model lock: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("contract lock must be a JSON object")
    return validate_model(data.get("model"))


def model_mismatch(worker: str, expected: str, actual: Any) -> str:
    """Format only non-sensitive effective-model diagnostic fields."""
    return (
        f"worker={worker} expected_model={expected} "
        f"effective_model={actual}"
    )
