import json
import os
import uuid
from pathlib import Path

import pytest

from agentteams.hiclaw_client import HiclawClient
from agentteams.worker_payloads import CORE_AGENTS, WORKERS

pytestmark = pytest.mark.agentteams
ROOT = Path(__file__).resolve().parents[2]
RUN_LIVE = os.environ.get("ARGUS_AGENTTEAMS_E2E") == "1"


@pytest.fixture(scope="module")
def hiclaw():
    return HiclawClient()


def test_workers_listable(hiclaw):
    workers = hiclaw.get_workers()
    assert isinstance(workers, list)


def test_six_core_workers_resident(hiclaw):
    workers = {w.get("name") for w in hiclaw.get_workers()}
    for agent in CORE_AGENTS:
        worker = WORKERS[agent]
        assert worker.name in workers, f"{worker.name} not registered"
        phase_state = hiclaw.get_workers(worker.name)
        assert phase_state, f"{worker.name} not found"
        assert phase_state[0]["phase"] == "Running", f"{worker.name} not Running"
        observed = hiclaw.get_worker_skill_observation(worker.name)
        ready = {skill.get("name") for skill in observed.get("skills", [])
                 if skill.get("ready")}
        assert ready == set(worker.skills), (
            f"{worker.name}: {ready} != {set(worker.skills)}")


def test_locked_skill_assignments_match_workers():
    lock = json.loads((ROOT / "skills/skills.lock.json").read_text(encoding="utf-8"))
    expected = {worker.name: list(worker.skills) for worker in WORKERS.values()}
    assert lock["assignments"] == expected
    assert {s["name"] for s in lock["skills"]} == {
        skill for assigned in expected.values() for skill in assigned
    }
