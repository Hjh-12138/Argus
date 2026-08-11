"""Synchronize the locked model and remote Skills to Argus Workers."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.model_config import load_locked_model, model_mismatch
from agentteams.worker_payloads import CORE_AGENTS, WORKERS, WORKER_RUNTIME


@dataclass
class SyncResult:
    model: str
    workers: list[dict]
    errors: list[str]


def _load_skill_lock(workspace: Path) -> dict:
    path = workspace / "skills" / "skills.lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    versions = {str(item["name"]): str(item["version"])
                for item in data["skills"]}
    return {"source": str(data.get("source", "")),
            "auth_type": str(data.get("auth_type", "none")),
            "versions": versions}


def capture_worker_snapshot(client: HiclawClient, workspace: Path) -> Path:
    """Write a credential-free snapshot of the six current Workers."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = workspace / ".argus" / "model-config" / stamp
    root.mkdir(parents=True, exist_ok=True)
    rows = [client.worker_configuration(WORKERS[agent].name)
            for agent in CORE_AGENTS]
    path = root / "workers-before.json"
    path.write_text(json.dumps({"workers": rows}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _verify_worker(client: HiclawClient, agent: str, expected: str,
                   timeout_s: int) -> dict:
    worker = WORKERS[agent]
    if not client.wait_ready(worker.name, timeout_s):
        raise HiclawError(f"worker={worker.name} did not become ready")
    actual = client.get_worker_effective_model(worker.name)
    if actual != expected:
        raise HiclawError(model_mismatch(worker.name, expected, actual))
    state = client.worker_configuration(worker.name)
    expected_skills = set(worker.skills)
    actual_skills = set(state.get("skills", []))
    if actual_skills != expected_skills:
        raise HiclawError(
            f"worker={worker.name} expected_skills={sorted(expected_skills)} "
            f"ready_skills={sorted(actual_skills)}"
        )
    return state


def sync_workers(client: HiclawClient, workspace: Path,
                 timeout_s: int = 300) -> SyncResult:
    model = load_locked_model(workspace / "agentteams" / "contract.lock.json")
    skill_lock = _load_skill_lock(workspace)
    applied = []
    for agent in CORE_AGENTS:
        worker = WORKERS[agent]
        versions = {skill: skill_lock["versions"][skill] for skill in worker.skills}
        client.apply_worker_remote_skills(
            worker.name, model, WORKER_RUNTIME, "", skill_lock["source"],
            skill_lock["auth_type"], versions)
        applied.append(worker.name)

    states = [_verify_worker(client, agent, model, timeout_s) for agent in CORE_AGENTS]
    return SyncResult(model=model, workers=states, errors=[])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    client = HiclawClient()
    try:
        snapshot = capture_worker_snapshot(client, workspace)
        if args.snapshot_only:
            print(json.dumps({"snapshot": str(snapshot)}, ensure_ascii=False))
            return 0
        result = sync_workers(client, workspace, args.timeout)
        print(json.dumps({"snapshot": str(snapshot), **asdict(result)},
                         ensure_ascii=False))
        return 0
    except (ValueError, HiclawError, OSError, json.JSONDecodeError) as exc:
        print(f"[apply-worker-config] ERROR: {exc}", file=__import__("sys").stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
