#!/usr/bin/env python3
"""argus-evidence-verify: standalone Meta evidence quality gate.

Reads a JSON input (snapshot + agent_results), validates every finding's
path/line/hash/evidence/actionability, and emits a list of MetaDecision objects.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

# Executor runs from skillPath without PYTHONPATH; ensure the skill root is
# on sys.path so that `implementation.meta` resolves correctly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from implementation.meta import (
    AgentResult, Evidence, Finding, MetaReviewer,
    SnapshotFile, SourceSnapshot,
)


def _parse_finding(raw: dict) -> Finding:
    evidence = None
    if raw.get("evidence"):
        ev = raw["evidence"]
        ctx = ev.get("context_lines")
        if isinstance(ctx, list):
            ctx = tuple(ctx)
        evidence = Evidence(
            context_lines=ctx or (),
            source_sha256=ev.get("source_sha256"),
            redacted_value=ev.get("redacted_value"),
            detector=ev.get("detector", ""),
        )
    return Finding(
        id=raw["id"],
        agent=raw.get("agent", ""),
        category=raw.get("category", ""),
        severity=raw.get("severity", "info"),
        confidence=float(raw.get("confidence", 0)),
        title=raw.get("title", ""),
        detail=raw.get("detail", ""),
        remediation=raw.get("remediation", ""),
        verification=raw.get("verification", ""),
        fingerprint=raw.get("fingerprint", ""),
        rule_id=raw.get("rule_id", ""),
        rule_version=raw.get("rule_version", ""),
        evidence=evidence,
        file=raw.get("file"),
        line_start=raw.get("line_start"),
        line_end=raw.get("line_end"),
    )


def _parse_result(raw: dict) -> AgentResult:
    findings = tuple(_parse_finding(f) for f in raw.get("findings", []))
    return AgentResult(
        agent=raw.get("agent", ""),
        agent_version_id=raw.get("agent_version_id", ""),
        status=raw.get("status", "completed"),
        required=bool(raw.get("required", True)),
        findings=findings,
        input_snapshot_id=raw.get("input_snapshot_id", ""),
        rule_set_version=raw.get("rule_set_version", ""),
        dataset_version=raw.get("dataset_version", ""),
    )


def invoke(payload: dict) -> dict:
    """Invoke MetaReviewer from a JSON payload dict (used by agent adapter and CLI)."""
    snapshot_raw = payload["snapshot"]
    snapshot = SourceSnapshot(
        root=snapshot_raw["root"],
        files=tuple(
            SnapshotFile(path=f["path"], sha256=f["sha256"], size=f.get("size", 0))
            for f in snapshot_raw.get("files", [])
        ),
        snapshot_id=snapshot_raw.get("snapshot_id", ""),
    )
    results = tuple(_parse_result(r) for r in payload.get("agent_results", []))
    decisions = MetaReviewer().review(snapshot, results)
    # Executor expects a JSON object, not an array.
    return {"decisions": [asdict(d) for d in decisions]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = invoke(payload)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
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
