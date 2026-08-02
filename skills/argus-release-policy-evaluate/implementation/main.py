"""argus-release-policy-evaluate skill entrypoint."""
from __future__ import annotations

from dataclasses import asdict

from core.policy import evaluate_policy


def invoke(meta_decisions, agent_results, config, expected_required=None) -> dict:
    decision = evaluate_policy(meta_decisions, agent_results, config,
                               expected_required=expected_required)
    data = asdict(decision)
    data["reasons"] = list(data["reasons"])
    data["verified_finding_ids"] = list(data["verified_finding_ids"])
    data["blocking_finding_ids"] = list(data["blocking_finding_ids"])
    return data
