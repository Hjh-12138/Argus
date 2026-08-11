import json
from pathlib import Path

import pytest

from agentteams.apply_worker_config import sync_workers
from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.worker_payloads import CORE_AGENTS, WORKERS


def test_apply_rejects_placeholder_before_writing_yaml():
    client = HiclawClient.__new__(HiclawClient)
    client.container = "unused"
    client._docker_exec = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("invalid model must fail before docker exec")
    )
    client._run = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("invalid model must fail before hiclaw")
    )

    with pytest.raises(ValueError):
        client.apply_worker_remote_skills(
            "argus-code", "model", "openclaw", "", "nacos://nacos:8848/public",
            "nacos", {"argus-code-rule-scan": "0.0.6"},
        )


def test_effective_model_reads_sanitized_worker_state():
    client = HiclawClient.__new__(HiclawClient)
    client.get_workers = lambda name: [{
        "name": name, "phase": "Running", "model": "deepseek-v4-flash",
        "runtime": "openclaw", "image": "agentteams/worker-agent:test",
    }]
    assert client.get_worker_effective_model("argus-code") == "deepseek-v4-flash"


def write_locks(tmp_path: Path):
    skills = {skill for worker in WORKERS.values() for skill in worker.skills}
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "skills/skills.lock.json").write_text(json.dumps({
        "source": "nacos://nacos:8848/public",
        "auth_type": "nacos",
        "skills": [{"name": name, "version": "0.0.6"}
                   for name in sorted(skills)],
    }), encoding="utf-8")
    (tmp_path / "agentteams").mkdir(exist_ok=True)
    (tmp_path / "agentteams/contract.lock.json").write_text(
        '{"model":"deepseek-v4-flash"}', encoding="utf-8")


class FakeWorkerClient:
    def __init__(self, model="deepseek-v4-flash"):
        self.model = model
        self.applied = []

    def apply_worker_remote_skills(self, name, model, runtime, soul,
                                   source, auth_type, skill_versions):
        self.applied.append((name, model, runtime, skill_versions))

    def wait_ready(self, name, timeout_s):
        return True

    def get_worker_effective_model(self, name):
        return self.model

    def get_worker_skill_observation(self, name):
        worker = next(w for w in WORKERS.values() if w.name == name)
        return {"skills": [{"name": skill, "ready": True}
                            for skill in worker.skills]}

    def get_workers(self, name=None):
        names = [WORKERS[agent].name for agent in CORE_AGENTS] if name is None else [name]
        return [{"name": n, "phase": "Running", "model": self.model}
                for n in names]

    def worker_configuration(self, name):
        worker = next(w for w in WORKERS.values() if w.name == name)
        return {"name": name, "phase": "Running", "model": self.model,
                "runtime": "openclaw", "image": "test",
                "skills": list(worker.skills)}


def test_sync_applies_lock_model_to_all_workers(tmp_path: Path):
    write_locks(tmp_path)
    client = FakeWorkerClient()
    result = sync_workers(client, tmp_path, timeout_s=1)
    assert result.model == "deepseek-v4-flash"
    assert {row[0] for row in client.applied} == {w.name for w in WORKERS.values()}
    assert {row[1] for row in client.applied} == {"deepseek-v4-flash"}


def test_sync_fails_when_effective_model_is_wrong(tmp_path: Path):
    write_locks(tmp_path)
    with pytest.raises(HiclawError, match="effective_model=model"):
        sync_workers(FakeWorkerClient("model"), tmp_path, timeout_s=1)
