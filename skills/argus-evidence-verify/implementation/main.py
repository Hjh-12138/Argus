"""argus-evidence-verify skill entrypoint.

该入口接收内存中的领域对象，由 AgentTeams Worker adapter 负责 JSON artifact 与对象转换。
"""
from __future__ import annotations

from dataclasses import asdict

from core.meta import MetaReviewer


def invoke(snapshot, agent_results) -> list[dict]:
    decisions = MetaReviewer().review(snapshot, tuple(agent_results))
    return [asdict(d) for d in decisions]
