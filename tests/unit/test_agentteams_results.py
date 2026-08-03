import json
import unittest
from pathlib import Path

from agentteams.hiclaw_client import HiclawError
from agentteams.orchestrator import Orchestrator


class ResultClient:
    def __init__(self, artifact):
        self.data = {
            "projects/project-one/meta.json": json.dumps({
                "project_id": "project-one",
                "project_room_id": "!room:matrix",
                "snapshot_id": "a" * 64,
                "tasks": ["project-one-assessor-sec"],
            }),
            "tasks/project-one-assessor-sec/meta.json": json.dumps({
                "task_id": "project-one-assessor-sec",
                "kind": "assessor",
                "agent": "sec",
                "status": "assigned",
                "required": True,
            }),
            "projects/project-one/plan.md": (
                "- [~] project-one-assessor-sec — assessor:sec\n"
            ),
            "tasks/project-one-assessor-sec/result.md": (
                "## Outcome\n\n**Status**: SUCCESS\n\n"
                "## Summary\n\ncomplete\n"
            ),
            "tasks/project-one-assessor-sec/artifacts/agent-result.json":
                json.dumps(artifact),
        }

    def pull_shared_directory(self, path):
        return None

    def read_shared_text(self, path):
        return self.data[path]

    def shared_exists(self, path):
        return path in self.data

    def write_shared_text(self, path, content):
        self.data[path] = content

    def sync_shared_directory(self, path):
        return None


class ResultValidationTests(unittest.TestCase):
    def _ingest(self, artifact):
        orchestrator = Orchestrator(
            ResultClient(artifact), Path.cwd(), model="deepseek-v4-flash")
        return orchestrator.ingest_task_result(
            "project-one", "project-one-assessor-sec")

    @staticmethod
    def _artifact(**overrides):
        artifact = {
            "agent": "sec",
            "status": "completed",
            "input_snapshot_id": "a" * 64,
            "findings": [],
        }
        artifact.update(overrides)
        return artifact

    def test_success_rejects_failed_machine_artifact(self):
        with self.assertRaisesRegex(HiclawError, "completed"):
            self._ingest(self._artifact(status="failed"))

    def test_success_rejects_machine_artifact_for_another_snapshot(self):
        with self.assertRaisesRegex(HiclawError, "snapshot"):
            self._ingest(self._artifact(input_snapshot_id="b" * 64))


if __name__ == "__main__":
    unittest.main()
