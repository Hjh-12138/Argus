#!/usr/bin/env python3
"""Argus thin CLI — sends audit requests to the Manager Agent via Matrix DM.

Replaces the monolithic orchestrator.py. All coordination logic now lives
in the Manager Agent (LLM-driven), which uses typed tasks to drive Workers.

Usage:
    python -m agentteams.cli audit \\
        --focus security,dependencies \\
        --title "Audit PR #42" \\
        [--snapshot-id <sha256>] \\
        [--project-id <custom-id>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from agentteams.hiclaw_client import HiclawClient, HiclawError

FOCUS_TO_ASSESSORS = {
    "security": ["sec"],
    "dependencies": ["dep"],
    "code": ["code"],
    "ci": ["delivery"],
    "full": ["dep", "code", "sec", "delivery"],
}


def _send_audit_request(client: HiclawClient, payload: dict) -> str:
    """Send an audit request to the Manager via admin DM room."""
    state = json.loads(client._docker_exec(
        "agentteams-manager",
        "cat", "/root/manager-workspace/state.json",
    ))
    admin_room = state.get("admin_dm_room_id")
    if not admin_room:
        raise HiclawError("Admin DM room not found in state.json. Run Manager onboarding first.")

    run_id = payload.get("run_id") or f"argus-run-{uuid.uuid4().hex[:12]}"
    focus = payload.get("focus", ["full"])
    assessors = []
    for f in focus:
        assessors.extend(FOCUS_TO_ASSESSORS.get(f, []))
    assessors = sorted(set(assessors))

    message = (
        f"**New Audit Request**\n\n"
        f"Run ID: `{run_id}`\n"
        f"Title: {payload.get('title', 'Untitled Audit')}\n"
        f"Focus: {', '.join(focus)}\n"
        f"Assessors: {', '.join(assessors)}\n"
    )
    if payload.get("snapshot_id"):
        message += f"Snapshot: `{payload['snapshot_id']}`\n"
    if payload.get("project_id"):
        message += f"Project ID: `{payload['project_id']}`\n"

    message += "\nPlease plan and dispatch the audit DAG."

    client.send_project_message(admin_room, message)
    print(f"[argus] Audit request sent to Manager (run_id={run_id})")
    print(f"[argus] Focus: {focus} → Assessors: {assessors}")
    print(f"[argus] The Manager will create the project and dispatch workers.")
    print(f"[argus] Check Matrix for progress updates.")
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Argus Audit CLI")
    sub = parser.add_subparsers(dest="command")

    audit_parser = sub.add_parser("audit", help="Send an audit request to the Manager Agent")
    audit_parser.add_argument("--focus", default="full",
                              help="Audit focus: security,dependencies,code,ci,full")
    audit_parser.add_argument("--title", default="Argus Audit",
                              help="Audit title")
    audit_parser.add_argument("--snapshot-id", help="Snapshot hash")
    audit_parser.add_argument("--project-id", help="Custom project ID")

    args = parser.parse_args(argv)
    if args.command != "audit":
        parser.print_help()
        return 1

    focus = [f.strip() for f in args.focus.split(",") if f.strip()]
    unknown = set(focus) - set(FOCUS_TO_ASSESSORS)
    if unknown:
        print(f"Unknown focus: {unknown}. Valid: {list(FOCUS_TO_ASSESSORS)}", file=sys.stderr)
        return 1

    try:
        client = HiclawClient()
        _send_audit_request(client, {
            "focus": focus,
            "title": args.title,
            "snapshot_id": args.snapshot_id,
            "project_id": args.project_id,
        })
    except HiclawError as exc:
        print(f"[argus] Error: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
