"""结果校验下沉（R1.2）：在每个 agent 输出边界跑 verify_finding。

三层校验（格式 / 事实 / 一致性）中，确定性可下沉的是「格式 + 事实（引用）」。
语义一致性需 LLM 研判（P6），不在此模块；降级方向必须 fail-closed（P3）——
幻觉 finding 直接拦截，绝不进入下游（宁 unknown 不 pass）。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.meta import MetaDecision, verify_finding
from core.schemas import AgentResult, Finding, SourceSnapshot


@dataclass(frozen=True)
class ResultVerification:
    agent: str
    passed: bool
    hallucinated_finding_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    decisions: tuple[MetaDecision, ...]
    clean_findings: tuple[Finding, ...]


def verify_agent_result(snapshot: SourceSnapshot,
                        result: AgentResult) -> ResultVerification:
    """对单个 AgentResult 的所有 finding 做边界校验，拦截引用型幻觉。"""
    decisions = tuple(verify_finding(snapshot, f) for f in result.findings)
    hallucinated = tuple(
        f.id for f, d in zip(result.findings, decisions)
        if d.label == "HALLUCINATION"
    )
    reason_codes = tuple(
        rc for d in decisions if d.label == "HALLUCINATION"
        for rc in d.reason_codes
    )
    clean = tuple(
        f for f, d in zip(result.findings, decisions)
        if d.label != "HALLUCINATION"
    )
    return ResultVerification(
        agent=result.agent,
        passed=not hallucinated,
        hallucinated_finding_ids=hallucinated,
        reason_codes=reason_codes,
        decisions=decisions,
        clean_findings=clean,
    )
