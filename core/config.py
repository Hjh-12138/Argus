"""Argus v2 配置：schema 校验、precedence、redacted effective config。

优先级：CLI flags > env vars > project argus.yaml > user config > defaults。
未知字段默认报错；日志输出最终生效配置但隐藏密钥。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_BLOCK = {"critical", "high", "medium", "low", "info"}
ALLOWED_INCOMPLETE = {"unknown", "warn", "block"}
ALLOWED_TOP = {
    "policy", "llm", "output", "mcp", "agents", "storage", "attack",
    "matrix", "watch", "learning", "observability", "rag", "memory", "entry",
}


class ConfigValidationError(Exception):
    pass


@dataclass
class PolicyConfig:
    block_on: list[str] = field(default_factory=lambda: ["critical", "high"])
    min_confidence: float = 0.80
    require_quality_label: str = "VERIFIED"
    incomplete_run: str = "unknown"


@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    send_source: bool = False
    max_diff_bytes: int = 262144


@dataclass
class OutputConfig:
    directory: str = ".argus/reports"
    retain_runs: int = 30


@dataclass
class McpConfig:
    network: str = "metadata_only"  # 固定值：只出网查元数据
    allowlist: list[dict] = field(default_factory=list)
    per_agent: dict = field(default_factory=dict)
    max_response_bytes: int = 262144
    timeout_seconds: int = 15


@dataclass
class Config:
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    mcp: McpConfig = field(default_factory=McpConfig)


def _parse_yaml_simple(text: str) -> dict:
    """极简 YAML 子集解析（初赛内嵌；Phase 2 替换为 PyYAML）。"""
    out: dict = {}
    section: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            if line.rstrip().endswith(":"):
                section = line.rstrip().rstrip(":").strip()
                out[section] = {}
            elif ":" in line:
                key, _, value = line.partition(":")
                out[key.strip()] = value.strip().strip("'\"")
                section = None
        elif section and ":" in line:
            k, _, v = line.strip().partition(":")
            v = v.strip().strip("'\"")
            if v.startswith("[") and v.endswith("]"):
                out[section][k.strip()] = [
                    x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()
                ]
            else:
                out[section][k.strip()] = v
    return out


def load_config(cli_args: list[str], project_path: Path, env=os.environ) -> Config:
    """加载配置。project_path 下的 argus.yaml 为项目级配置。"""
    project_file = Path(project_path) / "argus.yaml"
    data: dict = {}
    if project_file.exists():
        data = _parse_yaml_simple(project_file.read_text(encoding="utf-8"))
    _validate(data)
    cfg = _from_dict(data, env)
    _apply_cli(cfg, cli_args)
    return cfg


def _validate(data: dict):
    for k in data:
        if k not in ALLOWED_TOP:
            raise ConfigValidationError(f"unknown field: {k}")
    pol = data.get("policy", {})
    if not isinstance(pol, dict):
        raise ConfigValidationError("policy must be a mapping")
    for b in pol.get("block_on", []):
        if b not in ALLOWED_BLOCK:
            raise ConfigValidationError(f"invalid block_on: {b}")
    if pol.get("incomplete_run", "unknown") not in ALLOWED_INCOMPLETE:
        raise ConfigValidationError("incomplete_run must be unknown|warn|block")
    mcp = data.get("mcp", {})
    if mcp and isinstance(mcp, dict) and mcp.get("network", "metadata_only") != "metadata_only":
        raise ConfigValidationError("mcp.network must be metadata_only")


def _from_dict(data: dict, env) -> Config:
    pol = data.get("policy") or {}
    llm = data.get("llm") or {}
    out = data.get("output") or {}
    mcp = data.get("mcp") or {}

    def _bool(v) -> bool:
        return str(v).strip().lower() in ("true", "1", "yes", "on")

    def _int(v, default: int) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return Config(
        policy=PolicyConfig(
            block_on=list(pol.get("block_on", ["critical", "high"])),
            min_confidence=float(pol.get("min_confidence", 0.80)),
            require_quality_label=pol.get("require_quality_label", "VERIFIED"),
            incomplete_run=pol.get("incomplete_run", "unknown"),
        ),
        llm=LLMConfig(
            base_url=env.get("ARGUS_LLM_BASE_URL") or str(llm.get("base_url", "")),
            api_key=env.get("ARGUS_LLM_API_KEY") or str(llm.get("api_key", "")),
            model=env.get("ARGUS_LLM_MODEL") or str(llm.get("model", "")),
            send_source=_bool(llm.get("send_source", False)),
            max_diff_bytes=_int(llm.get("max_diff_bytes", 262144), 262144),
        ),
        output=OutputConfig(
            directory=str(out.get("directory", ".argus/reports")),
            retain_runs=_int(out.get("retain_runs", 30), 30),
        ),
        mcp=McpConfig(
            network=str(mcp.get("network", "metadata_only")),
            allowlist=list(mcp.get("allowlist", [])),
            per_agent=dict(mcp.get("per_agent", {})),
            max_response_bytes=_int(mcp.get("max_response_bytes", 262144), 262144),
            timeout_seconds=_int(mcp.get("timeout_seconds", 15), 15),
        ),
    )


def _apply_cli(cfg: Config, cli_args: list[str]):
    for i, a in enumerate(cli_args):
        if a == "--block-on" and i + 1 < len(cli_args):
            cfg.policy.block_on = [x for x in cli_args[i + 1].split(",") if x]


def effective_config_summary(cfg: Config) -> str:
    """日志输出最终生效配置，隐藏密钥与授权材料。"""
    llm = dict(cfg.llm.__dict__)
    llm["api_key"] = "***" if llm["api_key"] else ""
    return str({
        "policy": cfg.policy.__dict__,
        "llm": llm,
        "output": cfg.output.__dict__,
        "mcp": {"network": cfg.mcp.network,
                "allowlist": [a.get("name") for a in cfg.mcp.allowlist]},
    })
