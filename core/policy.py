"""确定性发布门禁：Reviewed Finding -> release_gate。

只有 VERIFIED 且 confidence 达阈值的 finding 参与默认阻断；required Agent 未完成时
不得 pass，返回 unknown。Attack verdict 不参与本模块。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.config import Config
from core.meta import MetaDecision
from core.schemas import AgentResult


@dataclass(frozen=True)
class PolicyDecision:
    release_gate: str  # pass | warn | block | unknown
    reasons: tuple[str, ...]
    verified_finding_ids: tuple[str, ...]
    blocking_finding_ids: tuple[str, ...]
    policy_version: str = "1"


def evaluate_policy(decisions: list[MetaDecision] | tuple[MetaDecision, ...],
                    results: list[AgentResult] | tuple[AgentResult, ...],
                    cfg: Config,
                    expected_required: set[str] | None = None) -> PolicyDecision:
    expected = expected_required or {r.agent for r in results if r.required}
    completed = {r.agent for r in results if r.status == "completed"}
    incomplete = sorted(expected - completed)
    failed_required = sorted(
        r.agent for r in results if r.required and r.status != "completed"
    )
    incomplete = sorted(set(incomplete + failed_required))
    if incomplete:
        return PolicyDecision(
            release_gate="unknown",
            reasons=(f"required agent(s) incomplete: {', '.join(incomplete)}",),
            verified_finding_ids=(),
            blocking_finding_ids=(),
        )

    meta_by_id = {d.finding_id: d for d in decisions}
    verified: list[str] = []
    blocking: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    for result in results:
        for finding in result.findings:
            decision = meta_by_id.get(finding.id)
            if decision is None or decision.label != cfg.policy.require_quality_label:
                continue
            if finding.confidence < cfg.policy.min_confidence:
                continue
            verified.append(finding.id)
            if finding.severity in cfg.policy.block_on:
                blocking.append(finding.id)
                reasons.append(
                    f"blocked by {finding.agent}/{finding.category} ({finding.severity})"
                )
            elif finding.severity == "medium":
                warnings.append(finding.id)
                reasons.append(
                    f"warning from {finding.agent}/{finding.category} (medium)"
                )

    if blocking:
        gate = "block"
    elif warnings:
        gate = "warn"
    else:
        gate = "pass"
        reasons.append("no verified blocking findings")

    return PolicyDecision(
        release_gate=gate,
        reasons=tuple(reasons),
        verified_finding_ids=tuple(verified),
        blocking_finding_ids=tuple(blocking),
    )
