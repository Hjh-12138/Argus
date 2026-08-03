import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "agentteams/contract.lock.json"


def _load_lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _hiclaw(*args: str) -> subprocess.CompletedProcess[str]:
    lock = _load_lock()
    return subprocess.run(
        ["docker", "exec", lock["manager_container"], "hiclaw", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_cli_entrypoint_reachable():
    result = _hiclaw("get", "workers", "-o", "json")
    assert result.returncode == 0, (
        f"hiclaw unreachable: {result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    assert isinstance(payload.get("workers"), list)
    assert payload.get("total") == len(payload["workers"])


def test_contract_lock_matches_pinned_environment():
    lock = _load_lock()
    assert lock["schema_version"] == "1"
    assert lock["agentteams_version"] == "v1.2.0-beta.1"
    assert lock["commit"] == "78d0ceda336befa6e62bf89fc1a6b08b965e128d"
    assert lock["cli_entrypoint"] == "docker exec agentteams-manager hiclaw"
    assert lock["verified_commands"] == [
        "create", "get", "apply", "delete", "update", "status",
    ]
    assert lock["embedded_image_digest"].startswith("sha256:")


def test_required_containers_are_running():
    lock = _load_lock()
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    running = set(result.stdout.splitlines())
    assert lock["manager_container"] in running
    assert lock["controller_container"] in running
