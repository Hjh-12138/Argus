#!/usr/bin/env python3
"""argus-report-materialize: standalone deterministic report writer.

Reads JSON input (snapshot + agent_results + meta_decisions + policy),
atomically writes report.json + report.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from implementation.report import render_report, write_report


def invoke(payload: dict) -> dict:
    """Invoke report generation from a JSON payload dict."""
    run_id = payload["run_id"]
    snapshot = payload["snapshot"]
    results = payload.get("agent_results", [])
    meta_decisions = payload.get("meta_decisions", [])
    policy = payload.get("policy", payload.get("policy_decision", {}))
    output_dir = payload.get("output_dir", ".")

    data = render_report(run_id, snapshot, results, meta_decisions, policy)
    json_path, md_path = write_report(output_dir, data)
    return {"status": "succeeded", "report_json": str(json_path),
            "report_md": str(md_path)}


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
