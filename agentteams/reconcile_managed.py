"""R4.1 接入 AgentTeams 路径：读回共享状态 → 重算 gate → 对账 LLM 报告。

AgentTeams 路径的 report.json 由 Manager LLM 写出（不可信）。本模块从共享存储
读回 assessor findings（dep/code/sec/delivery-findings.json）+ meta decisions
（meta-decisions.json）——这些是 worker 用确定性 skill 产出的机器产物——然后用
确定性 policy 重算 gate，并对账报告（区分「编造」与「篡改」），不信任 LLM 自述 gate。

产物缺失/不可解析时按 fail-closed 处理：该域标 failed → policy 出 unknown（P3）。
"""
from __future__ import annotations

import json

from agentteams.hiclaw_client import HiclawError
from core.meta import MetaDecision
from core.policy import evaluate_policy
from core.reconcile import reconcile_report
from core.schemas import AgentResult, Evidence, Finding

ASSESSOR_ROLES = ("dep", "code", "sec", "delivery")


# ---- 宽容的产物解析（worker 聚合格式不唯一） ----

def extract_findings(data) -> list[dict]:
    """从已解析的 JSON 里抽出 finding dict 列表，容忍多种聚合格式。"""
    if isinstance(data, list):
        items: list[dict] = []
        for x in data:
            if isinstance(x, dict) and isinstance(x.get("finding"), dict):
                items.append(x["finding"])          # finding-emit wrapper
            elif isinstance(x, dict) and "id" in x:
                items.append(x)                     # 裸 finding dict
        return items
    if isinstance(data, dict):
        if isinstance(data.get("findings"), list):
            return [x for x in data["findings"] if isinstance(x, dict)]
        if isinstance(data.get("finding"), dict):
            return [data["finding"]]
    return []


def extract_decisions(data) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("decisions"), list):
        return [d for d in data["decisions"] if isinstance(d, dict)]
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return []


def parse_findings(text: str) -> list[dict]:
    try:
        return extract_findings(json.loads(text))
    except json.JSONDecodeError:
        return []


def parse_decisions(text: str) -> list[dict]:
    try:
        return extract_decisions(json.loads(text))
    except json.JSONDecodeError:
        return []


# ---- 重建 host 类型 ----

def finding_from_dict(d: dict) -> Finding | None:
    """宽容地把 finding dict 转成 host Finding；字段非法返回 None（跳过）。"""
    try:
        evidence = None
        ev = d.get("evidence")
        if isinstance(ev, dict):
            ctx = ev.get("context_lines")
            evidence = Evidence(
                context_lines=tuple(ctx) if isinstance(ctx, (list, tuple)) else (),
                source_sha256=ev.get("source_sha256"),
                redacted_value=ev.get("redacted_value"),
                detector=ev.get("detector", ""),
            )
        return Finding(
            id=str(d.get("id", "")),
            agent=str(d.get("agent", "")),
            category=str(d.get("category", "")),
            severity=d.get("severity", "info"),
            confidence=float(d.get("confidence", 0)),
            title=str(d.get("title", "")),
            detail=str(d.get("detail", "")),
            remediation=str(d.get("remediation", "")),
            verification=str(d.get("verification", "")),
            fingerprint=str(d.get("fingerprint", "")),
            rule_id=str(d.get("rule_id", "")),
            rule_version=str(d.get("rule_version", "")),
            evidence=evidence,
            file=d.get("file"),
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
        )
    except (ValueError, TypeError):
        return None


def decision_from_dict(d: dict) -> MetaDecision:
    return MetaDecision(
        finding_id=str(d.get("finding_id", "")),
        label=d.get("label", "NEEDS_EVIDENCE"),
        reason_codes=tuple(d.get("reason_codes") or ()),
        detail=str(d.get("detail", "")),
        checked_source_sha256=d.get("checked_source_sha256"),
    )


def result_from(agent: str, findings: tuple[Finding, ...],
                status: str = "completed") -> AgentResult:
    return AgentResult(
        agent=agent, agent_version_id=f"{agent}-managed", status=status,
        required=True, findings=findings, input_snapshot_id="",
        rule_set_version="", dataset_version="", metrics={},
    )


# ---- 读回共享状态 ----

def read_assessor_findings(client, project_id: str,
                           role: str) -> tuple[Finding, ...] | None:
    """读回某 assessor 的机器产物。None = 产物缺失/不可解析（该域未审计）。"""
    path = f"projects/{project_id}/{role}-findings.json"
    try:
        text = client.read_shared_text(path, refresh=True)
        data = json.loads(text)
    except (HiclawError, json.JSONDecodeError):
        return None
    items = extract_findings(data)
    return tuple(
        f for f in (finding_from_dict(d) for d in items) if f is not None)


def read_meta_decisions(client, project_id: str) -> list[MetaDecision] | None:
    path = f"projects/{project_id}/meta-decisions.json"
    try:
        text = client.read_shared_text(path, refresh=True)
        data = json.loads(text)
    except (HiclawError, json.JSONDecodeError):
        return None
    return [decision_from_dict(d) for d in extract_decisions(data)]


# ---- 对账入口 ----

def reconcile_managed_report(client, project_id: str, report: dict,
                             cfg) -> dict:
    """读回共享状态 → 重算 gate → 对账报告，返回修复后的 report dict。"""
    results: list[AgentResult] = []
    for role in ASSESSOR_ROLES:
        findings = read_assessor_findings(client, project_id, role)
        if findings is None:
            results.append(result_from(role, (), "failed"))  # fail-closed
        else:
            results.append(result_from(role, findings, "completed"))

    decisions = read_meta_decisions(client, project_id) or []

    policy = evaluate_policy(tuple(decisions), tuple(results), cfg)
    rec = reconcile_report(report, tuple(results), tuple(decisions), policy)
    return rec.repaired_report
