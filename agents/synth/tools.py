"""Synth 工具入口：只消费 Meta 审核结果，不重新扫描源码。"""
from __future__ import annotations

from core.policy import evaluate_policy
from core.report import render_report, write_report


def synthesize(run_id, snapshot, agent_results, meta_decisions, config, coverage=None):
    expected = {r.agent for r in agent_results if r.required}
    policy = evaluate_policy(meta_decisions, agent_results, config,
                             expected_required=expected)
    report = render_report(run_id, snapshot, tuple(agent_results),
                           tuple(meta_decisions), policy, coverage=coverage)
    return policy, report
