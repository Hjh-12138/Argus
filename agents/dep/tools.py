"""Dependency Auditor 工具边界。

初赛仅允许读取快照和固定 registry fixture；禁止安装依赖、执行 package scripts、
或因单次超时判定包不存在。
"""
from __future__ import annotations

import json
from pathlib import Path


def load_registry_fixture(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("registry fixture must be a JSON object")
    for package, entry in data.items():
        if not isinstance(package, str) or not isinstance(entry, dict):
            raise ValueError("invalid registry fixture entry")
        if "exists" not in entry or not isinstance(entry["exists"], bool):
            raise ValueError(f"registry entry {package!r} must declare boolean exists")
    return data
