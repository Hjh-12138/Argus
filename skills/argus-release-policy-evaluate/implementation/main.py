#!/usr/bin/env python3
"""argus-release-policy-evaluate: standalone deterministic release gate.

No host imports. Consumes Meta-reviewed decisions and AgentResult summaries,
applies the policy configuration, and emits a PolicyDecision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class SkillError(Exception):
    pass


def invoke(payload: dict) -> dict:
    decisions = payload.get("meta_decisions") or payload.get("decisions", [])
    results = payload.get("agent_results") or payload.get("results", [])
    policy = payload.get("policy", {})
    require_label = policy.get("require_quality_label", "VERIFIED")
    min_confidence = float(policy.get("min_confidence", 0.8))
    block_on = set(policy.get("block_on", ("critical", "high")))

    expected = {r["agent"] for r in results if r.get("required")}
    completed = {r["agent"] for r in results if r.get("status") == "completed"}
    incomplete = sorted(expected - completed)
    incomplete += [r["agent"] for r in results
                   if r.get("required") and r.get("status") != "completed"]
    incomplete = sorted(set(incomplete))
    if incomplete:
        return {"schema_version": "1", "status": "completed",
                "release_gate": "unknown",
                "reasons": [f"required agent(s) incomplete: {', '.join(incomplete)}"],
                "verified_finding_ids": [], "blocking_finding_ids": [],
                "policy_version": "1"}

    meta_by_id = {d["finding_id"]: d for d in decisions}
    verified: list[str] = []
    blocking: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    for result in results:
        for finding in result.get("findings", []):
            decision = meta_by_id.get(finding["id"])
            if decision is None or decision.get("label") != require_label:
                continue
            if float(finding.get("confidence", 0)) < min_confidence:
                continue
            verified.append(finding["id"])
            if finding.get("severity") in block_on:
                blocking.append(finding["id"])
                reasons.append(
                    f"blocked by {finding.get('agent')}/{finding.get('category')} "
                    f"({finding.get('severity')})")
            elif finding.get("severity") == "medium":
                warnings.append(finding["id"])
                reasons.append(
                    f"warning from {finding.get('agent')}/{finding.get('category')} (medium)")

    if blocking:
        gate = "block"
    elif warnings:
        gate = "warn"
    else:
        gate = "pass"
        reasons.append("no verified blocking findings")

    return {"schema_version": "1", "status": "completed",
            "release_gate": gate, "reasons": reasons,
            "verified_finding_ids": verified, "blocking_finding_ids": blocking,
            "policy_version": "1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = invoke(payload)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, SkillError) as exc:
        error = {"schema_version": "1", "status": "failed",
                 "error_code": "INVALID_INPUT", "error_message": str(exc)[:500]}
        Path(args.output).write_text(
            json.dumps(error, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
