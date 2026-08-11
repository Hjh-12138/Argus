from pathlib import Path

import pytest

from agentteams.hiclaw_client import HiclawError
from agentteams.room_audit import RoomDriver


class StageClient:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.messages = []

    def shared_exists(self, path, refresh=False):
        return path in self.existing

    def send_project_message(self, room_id, body, mentions=()):
        self.messages.append((room_id, body, tuple(mentions)))


def test_assessor_gate_accepts_role_artifact_aliases(tmp_path: Path):
    project = "argus-run-test"
    names = {
        f"projects/{project}/dep-findings.json",
        f"projects/{project}/findings-argus-code.md",
        f"projects/{project}/findings-sec.md",
        f"projects/{project}/findings-delivery.md",
    }
    driver = RoomDriver(StageClient(names), tmp_path,
                        poll_interval_s=0.001, deadline_s=0.01)
    driver._wait_for_assessors(project)


def test_assessor_gate_fails_when_a_role_is_missing(tmp_path: Path):
    project = "argus-run-test"
    names = {
        f"projects/{project}/dep-findings.json",
        f"projects/{project}/findings-argus-code.md",
        f"projects/{project}/findings-delivery.md",
    }
    driver = RoomDriver(StageClient(names), tmp_path,
                        poll_interval_s=0.001, deadline_s=0.01)
    with pytest.raises(HiclawError, match="findings-sec"):
        driver._wait_for_assessors(project)


def test_meta_and_synth_mentions_are_separate(tmp_path: Path):
    client = StageClient()
    driver = RoomDriver(client, tmp_path)
    driver._post_meta_stage("!room", "argus-run-test")
    driver._post_synth_stage("!room", "argus-run-test")
    assert client.messages[0][2] == ("@argus-meta:matrix-local.agentteams.io:18080",)
    assert client.messages[1][2] == ("@argus-synth:matrix-local.agentteams.io:18080",)
