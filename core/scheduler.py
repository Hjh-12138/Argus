"""确定性启发式调度（§7.2）。

- doc-only 变更 → intentional skip（不回退到 code，修复旧逻辑矛盾）；
- 路径/manifest/diff 结构决定最小 Agent 集；
- LLM confirmation 阶段在 Phase 2 接入，此处仅启发式（LLM 失败回退本函数）。
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

FILE_AGENT_MAP = {
    r"(^|/)package\.json$": {"dep"},
    r"(^|/)requirements.*\.txt$": {"dep"},
    r"(^|/)pyproject\.toml$": {"dep", "delivery"},
    r"(^|/)go\.mod$": {"dep"},
    r"(^|/)\.env($|\.)": {"sec", "delivery"},
    r"\.(yaml|yml|toml)$": {"sec", "delivery"},
    r"\.sql$": {"code", "sec", "perf"},
    r"(^|/)(middleware|auth|guard)(/|\.|$)": {"sec", "code"},
    r"(^|/)(migration|alembic)(/|\.|$)": {"delivery", "robust"},
    r"(\.test\.|\.spec\.|/tests?/|/__tests__/)": {"delivery"},
}

DOC_PATTERNS = (".md", ".rst", ".txt")
CODE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java")

# 启发式标为 mandatory、LLM 不可删除的 Agent（§7.1 安全约束）
MANDATORY_AGENTS = {"sec", "dep", "delivery"}


@dataclass(frozen=True)
class Change:
    path: str
    status: str
    is_comment_or_doc_only: bool = False
    contains_route_or_query: bool = False


@dataclass(frozen=True)
class ScheduleDecision:
    agents: set[str] = field(default_factory=set)
    reason: str = ""
    intentional_skip: bool = False

    @property
    def mandatory(self) -> set[str]:
        return self.agents & MANDATORY_AGENTS


def heuristic_schedule(changes: list[Change]) -> ScheduleDecision:
    if changes and all(c.is_comment_or_doc_only for c in changes):
        return ScheduleDecision(agents=set(), reason="doc_only", intentional_skip=True)

    agents: set[str] = set()
    for change in changes:
        for pattern, mapped in FILE_AGENT_MAP.items():
            if re.search(pattern, change.path, re.IGNORECASE):
                agents.update(mapped)
        if change.status in {"added", "modified", "renamed"} and change.path.endswith(
            CODE_EXTENSIONS
        ):
            agents.add("code")
        if change.contains_route_or_query:
            agents.update({"code", "sec", "perf"})

    directories = {posixpath.dirname(c.path) for c in changes}
    if len(directories) >= 3:
        agents.add("arch")

    if not agents:
        agents.add("code")

    return ScheduleDecision(agents=agents, reason="heuristic", intentional_skip=False)
