"""关键性分级 + 显式降级（R3.3）。

关键性判定方向保守（P3）：planner 只能**增加**关键 agent，不能删减 MANDATORY_AGENTS。
非关键 agent 失败 → 显式标注 NOT_AUDITED（coverage 写明「XX 域未审计」），绝不静默跳过；
关键 agent 失败 → 不可降级，必须走 HUMAN_WAIT / fail-closed unknown。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.scheduler import MANDATORY_AGENTS
from core.schemas import AgentResult


def critical_agents(planner_critical: set[str] | None = None) -> set[str]:
    """关键 agent 集合 = MANDATORY_AGENTS ∪ planner 标定（只增不减，宁保守）。"""
    base = set(MANDATORY_AGENTS)
    if planner_critical:
        base |= set(planner_critical)
    return base


@dataclass(frozen=True)
class Degradation:
    degraded_agents: tuple[str, ...]        # 非关键失败 agent（标 NOT_AUDITED）
    blocking_agents: tuple[str, ...]        # 关键失败 agent（不可降级）
    not_audited_domains: tuple[str, ...]    # 显式未审计域（= degraded）

    @property
    def can_continue(self) -> bool:
        return not self.blocking_agents


def classify_failures(results: tuple[AgentResult, ...] | list[AgentResult],
                      critical: set[str] | None = None) -> Degradation:
    """把失败 agent 分成「可降级(非关键)」与「阻断(关键)」两类。"""
    crit = critical if critical is not None else critical_agents()
    failed = sorted({r.agent for r in results if r.status != "completed"})
    degraded = [a for a in failed if a not in crit]
    blocking = [a for a in failed if a in crit]
    return Degradation(
        degraded_agents=tuple(degraded),
        blocking_agents=tuple(blocking),
        not_audited_domains=tuple(degraded),
    )
