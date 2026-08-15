"""LoongSuite OpenClaw OTel 插件配置生成器（观测接入 Task 1）。

为 AgentTeams 的 OpenClaw runtime（manager + worker）生成可复现的
`opentelemetry-instrumentation-openclaw` 插件配置条目。

P4 硬约束：conversation access 恒为关闭。版本 >= 2026.4.25 时显式写
`hooks.allowConversationAccess=false`；版本未知或低于阈值时省略 hooks 块
（低版本 OpenClaw 不认该字段会配置校验报错，且缺省即为 conversation access
关闭）——插件只上报结构 + token 计数，不采 prompt 正文/源码/密钥。
"""
from __future__ import annotations

import re

OPENTELEMETRY_PLUGIN_NAME = "opentelemetry-instrumentation-openclaw"
MIN_HOOKS_VERSION = "2026.4.25"   # OpenClaw 认识 hooks.allowConversationAccess 的最低版本
MIN_HOOKS_NUM = 20260425
_VERSION_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})")

ROLES = ("manager", "dep", "code", "sec", "delivery", "meta", "synth")


def _version_num(version: str | None) -> int | None:
    """解析 'YYYY.M.D' 为数值（对齐安装脚本 OC_NUM = M*10000+m*100+p）。

    version=None 表示未知 → 返回 None（保守：省略 hooks 块）；
    非 None 但解析失败 → 抛 ValueError（调用方传错，快速失败）。
    """
    if version is None:
        return None
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"cannot parse OpenClaw version: {version!r}")
    major, minor, patch = (int(group) for group in match.groups())
    return major * 10000 + minor * 100 + patch


def otel_plugin_entry(endpoint: str, service_name: str,
                      *, version: str | None = None) -> dict:
    """生成 `plugins.entries.opentelemetry-instrumentation-openclaw` 条目。

    返回形如
        {"enabled": True,
         "hooks": {"allowConversationAccess": False},      # 仅 version >= 2026.4.25
         "config": {"endpoint": ..., "serviceName": ...}}
    的 dict；version 未知或低于阈值时不带 hooks 块。
    """
    entry: dict = {
        "enabled": True,
        "config": {
            "endpoint": endpoint,
            "serviceName": service_name,
        },
    }
    num = _version_num(version)
    if num is not None and num >= MIN_HOOKS_NUM:
        entry["hooks"] = {"allowConversationAccess": False}
    return entry


def otel_service_name(role: str) -> str:
    """OpenClaw 观测的 service.name：manager → argus-manager，worker → argus-worker-<role>。"""
    if role == "manager":
        return "argus-manager"
    if role in ROLES:
        return f"argus-worker-{role}"
    raise ValueError(f"unknown Argus role: {role!r} (expected one of {ROLES})")
