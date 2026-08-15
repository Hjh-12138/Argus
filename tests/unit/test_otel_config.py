"""LoongSuite OpenClaw OTel 插件配置生成器纯逻辑测试（Task 1）。

P4 硬约束的验证核心：无论版本如何，conversation access 恒为关闭。
"""
from __future__ import annotations

import pytest

from agentteams.otel_config import (
    MIN_HOOKS_VERSION,
    OPENTELEMETRY_PLUGIN_NAME,
    otel_plugin_entry,
    otel_service_name,
)


# --- 常量 ---

def test_plugin_name_constant():
    assert OPENTELEMETRY_PLUGIN_NAME == "opentelemetry-instrumentation-openclaw"


def test_min_hooks_version_constant():
    assert MIN_HOOKS_VERSION == "2026.4.25"


# --- otel_plugin_entry：基础结构 ---

def test_entry_enables_and_injects_endpoint_and_service():
    entry = otel_plugin_entry("http://argus-jaeger:4318", "argus-manager",
                              version="2026.5.12")
    assert entry["enabled"] is True
    assert entry["config"]["endpoint"] == "http://argus-jaeger:4318"
    assert entry["config"]["serviceName"] == "argus-manager"


def test_entry_does_not_touch_headers_when_absent():
    entry = otel_plugin_entry("http://argus-jaeger:4318", "argus-worker-sec",
                              version="2026.5.12")
    assert "headers" not in entry["config"]


# --- otel_plugin_entry：版本分支 + P4 ---

@pytest.mark.parametrize("version", ["2026.4.25", "2026.5.12", "2026.05.12", "2027.1.1"])
def test_hooks_block_included_at_or_above_threshold(version):
    entry = otel_plugin_entry("e", "s", version=version)
    assert "hooks" in entry
    # P4：允许 conversation access 恒为 false，绝不为 true。
    assert entry["hooks"]["allowConversationAccess"] is False


@pytest.mark.parametrize("version", ["2026.4.24", "2025.12.31", "2024.1.1"])
def test_hooks_block_omitted_below_threshold(version):
    assert "hooks" not in otel_plugin_entry("e", "s", version=version)


def test_hooks_omitted_when_version_unknown():
    assert "hooks" not in otel_plugin_entry("e", "s")


def test_malformed_version_raises():
    with pytest.raises(ValueError):
        otel_plugin_entry("e", "s", version="not-a-version")


# --- otel_service_name ---

def test_service_name_manager():
    assert otel_service_name("manager") == "argus-manager"


@pytest.mark.parametrize("role,expected", [
    ("dep", "argus-worker-dep"),
    ("code", "argus-worker-code"),
    ("sec", "argus-worker-sec"),
    ("delivery", "argus-worker-delivery"),
    ("meta", "argus-worker-meta"),
    ("synth", "argus-worker-synth"),
])
def test_service_name_workers(role, expected):
    assert otel_service_name(role) == expected


def test_service_name_unknown_role_raises():
    with pytest.raises(ValueError):
        otel_service_name("arch")
