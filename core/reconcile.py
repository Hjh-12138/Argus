"""报告溯源对账（R4.1）。

报告里的每一个关键数据、每一个结论，都要能追溯到共享状态里的对应字段和来源 agent。
对账区分两类问题：
- 「无依据」（编造）：report finding 的 id 在共享状态里找不到来源 → 剔除；
- 「被篡改」（不一致）：id 存在但 file/line/severity 与来源不符 → 标注，不剔除。

对账后 gate 从共享状态**重算**（不信任报告里 LLM 写的 gate，P5 独立验证）。
自由文本 summary 隔离标注、不参与 gate。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.policy import PolicyDecision
from core.schemas import AgentResult, Finding


def _source_findings(results) -> dict[str, Finding]:
    return {f.id: f for r in results for f in r.findings}


def _finding_matches(finding: Finding, item: dict) -> bool:
    return (item.get("file") == finding.file
            and item.get("line_start") == finding.line_start
            and item.get("line_end") == finding.line_end
            and item.get("severity") == finding.severity)


@dataclass(frozen=True)
class Reconciliation:
    gate_mismatch: bool
    recomputed_gate: str
    unfounded_finding_ids: tuple[str, ...]    # 编造
    inconsistent_finding_ids: tuple[str, ...]  # 篡改
    summary_flagged: bool
    repaired_report: dict


def reconcile_report(report: dict, results, meta_decisions,
                     policy: PolicyDecision) -> Reconciliation:
    """把 report 反查共享状态，返回对账结论与修复后的 report。"""
    sources = _source_findings(results)
    report_findings = list(report.get("findings") or [])
    unfounded: list[str] = []
    inconsistent: list[str] = []
    repaired_findings: list[dict] = []
    for item in report_findings:
        fid = item.get("id")
        src = sources.get(fid)
        if src is None:
            unfounded.append(fid)  # 编造：剔除
            continue
        entry = dict(item)
        if not _finding_matches(src, item):
            inconsistent.append(fid)
            entry["reconciliation_status"] = "INCONSISTENT"  # 篡改：标注
        else:
            entry["reconciliation_status"] = "OK"
        repaired_findings.append(entry)

    gate_mismatch = report.get("release_gate") != policy.release_gate
    summary_flagged = bool(report.get("summary"))

    repaired = dict(report)
    repaired["release_gate"] = policy.release_gate  # 从共享状态重算，不信任报告
    repaired["findings"] = repaired_findings
    repaired["reconciliation"] = {
        "gate_mismatch": gate_mismatch,
        "recomputed_gate": policy.release_gate,
        "unfounded_finding_ids": unfounded,
        "inconsistent_finding_ids": inconsistent,
        "summary_isolated": summary_flagged,
    }
    return Reconciliation(
        gate_mismatch=gate_mismatch,
        recomputed_gate=policy.release_gate,
        unfounded_finding_ids=tuple(unfounded),
        inconsistent_finding_ids=tuple(inconsistent),
        summary_flagged=summary_flagged,
        repaired_report=repaired,
    )
