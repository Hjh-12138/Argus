import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agentteams.hiclaw_client import HiclawError
from agentteams.project_driver import ProjectDriver
from agentteams.worker_payloads import SnapshotReference


class FakeClient:
    def __init__(self):
        self.tasks = {}
        self.dispatched = []
        self.artifacts = {}
        self.registered = []
        self.events = []
        self.project_room_id = "!argus-project:matrix.test"
        self.binary_files = {}

    def create_project(self, project_id: str, title: str, workers) -> dict:
        self.events.append(("create_project", project_id, tuple(workers)))
        return {
            "project_id": project_id,
            "project_room_id": self.project_room_id,
            "created_at": "2026-08-05T00:00:00Z",
        }

    def publish_shared_file(self, relative_path: str, source_path: Path) -> None:
        self.events.append(("publish_shared_file", relative_path))
        self.binary_files[relative_path] = Path(source_path).read_bytes()

    def register_task(self, request: dict) -> dict:
        self.events.append(("register_task", request["task_id"]))
        self.registered.append(request["task_id"])
        self.requests = getattr(self, "requests", [])
        self.requests.append(request)
        self.tasks[request["task_id"]] = {
            "task": {"task_id": request["task_id"], "assigned_worker": request["assigned_worker"],
                     "state": "REGISTERED", "revision": 1},
        }
        return self.tasks[request["task_id"]]

    def get_worker_skill_observation(self, worker: str) -> dict:
        return {
            "generation": "g" * 64,
            "skills": [
                {"name": "argus-dependency-inspect",
                 "observed_digest": "sha256:" + "d" * 64, "ready": True},
                {"name": "argus-code-rule-scan",
                 "observed_digest": "sha256:" + "c" * 64, "ready": True},
                {"name": "argus-secret-scan",
                 "observed_digest": "sha256:" + "b" * 64, "ready": True},
                {"name": "argus-ci-policy-check",
                 "observed_digest": "sha256:" + "a" * 64, "ready": True},
                {"name": "argus-evidence-verify",
                 "observed_digest": "sha256:" + "e" * 64, "ready": True},
                {"name": "argus-release-policy-evaluate",
                 "observed_digest": "sha256:" + "f" * 64, "ready": True},
                {"name": "argus-report-materialize",
                 "observed_digest": "sha256:" + "9" * 64, "ready": True},
                {"name": "argus-finding-emit",
                 "observed_digest": "sha256:" + "8" * 64, "ready": True},
            ],
        }

    def get_task(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise HiclawError("task not found")
        return self.tasks[task_id]

    def dispatch_task(self, task_id: str, revision: int) -> dict:
        self.dispatched.append(task_id)
        state = self.tasks[task_id]["task"]["state"]
        if state == "REGISTERED":
            self.tasks[task_id]["task"]["state"] = "DISPATCHED"
            self.tasks[task_id]["task"]["revision"] = revision + 1
        return self.tasks[task_id]["task"]

    def wait_task(self, task_id: str, terminal: set, timeout_s: int = 300) -> dict:
        return self.tasks[task_id]["task"]

    def ack_task(self, task_id: str, revision: int) -> dict:
        self.tasks[task_id]["task"]["state"] = "ACKNOWLEDGED"
        self.tasks[task_id]["task"]["revision"] = revision + 1
        return self.tasks[task_id]["task"]

    def start_task(self, task_id: str, revision: int) -> dict:
        self.tasks[task_id]["task"]["state"] = "RUNNING"
        self.tasks[task_id]["task"]["revision"] = revision + 1
        return self.tasks[task_id]["task"]

    def terminal_task(self, task_id: str, revision: int, state: str, code: str) -> dict:
        self.tasks[task_id]["task"]["state"] = state
        return self.tasks[task_id]["task"]

    def publish_shared_text(self, relative_path: str, content: str) -> None:
        self.events.append(("publish_shared_text", relative_path))

    def sync_shared_directory(self, relative_path: str) -> None:
        pass

    def pull_shared_directory(self, relative_path: str) -> None:
        pass

    def read_shared_text(self, relative_path: str) -> str:
        task_id = relative_path.split("/")[1]
        if task_id not in self.artifacts:
            raise HiclawError("no artifact")
        return json.dumps(self.artifacts[task_id])


class FakeAssessorClient(FakeClient):
    """Fake client that completes tasks immediately and stores artifacts."""

    def __init__(self, artifact_for=None):
        super().__init__()
        self.artifact_for = artifact_for or (lambda tid: {
            "schema_version": "1", "status": "completed",
            "agent": "x", "input_snapshot_id": "snap-1", "findings": [],
        })

    def dispatch_task(self, task_id: str, revision: int) -> dict:
        super().dispatch_task(task_id, revision)
        self.tasks[task_id]["task"]["state"] = "COMPLETED"
        self.tasks[task_id]["task"]["revision"] = revision + 2
        self.artifacts[task_id] = self.artifact_for(task_id)
        return self.tasks[task_id]["task"]


def _lock_file(workspace: Path) -> Path:
    lock = {
        "schema_version": "2", "source": "nacos://private/argus", "auth_type": "none",
        "skills": [
            {"name": "argus-dependency-inspect", "version": "1.0.0", "local_sha256": "a" * 64},
            {"name": "argus-code-rule-scan", "version": "1.0.0", "local_sha256": "b" * 64},
            {"name": "argus-secret-scan", "version": "1.0.0", "local_sha256": "c" * 64},
            {"name": "argus-ci-policy-check", "version": "1.0.0", "local_sha256": "d" * 64},
            {"name": "argus-finding-emit", "version": "1.0.0", "local_sha256": "e" * 64},
            {"name": "argus-evidence-verify", "version": "1.0.0", "local_sha256": "f" * 64},
            {"name": "argus-release-policy-evaluate", "version": "1.0.0", "local_sha256": "g" * 64},
            {"name": "argus-report-materialize", "version": "1.0.0", "local_sha256": "h" * 64},
        ],
        "assignments": {},
    }
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / "skills.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def _driver(client, tmp: Path) -> ProjectDriver:
    _lock_file(tmp)
    return ProjectDriver(client, tmp)


def _snapshot(tmp: Path) -> SnapshotReference:
    archive = tmp / "snapshot.zip"
    archive.write_bytes(b"PK\x03\x04typed-task-snapshot")
    return SnapshotReference(
        snapshot_id="snap-1", source_root="/root/hiclaw-fs/shared",
        files=({"path": "app.py", "sha256": "0" * 64,
                "size": 10, "language": "py"},),
        archive_path=str(archive),
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())


class ProjectDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_orders_assessors_meta_synth(self):
        client = FakeAssessorClient()
        outcome = _driver(client, self.tmp).run({"project_id": "proj-1"}, _snapshot(self.tmp))
        self.assertEqual(outcome.status, "completed")
        assessors = [f"proj-1-assessor-{r}" for r in ("dep", "code", "sec", "delivery")]
        self.assertEqual(client.registered[:4], assessors)
        self.assertIn("proj-1-meta", client.registered)
        self.assertIn("proj-1-synth", client.registered)
        self.assertEqual(outcome.gate, "unknown")

    def test_required_assessor_failure_gives_human_wait(self):
        class FailingAssessor(FakeAssessorClient):
            def dispatch_task(self, task_id, revision):
                super().dispatch_task(task_id, revision)
                if task_id == "proj-2-assessor-sec":
                    self.tasks[task_id]["task"]["state"] = "FAILED"
                return self.tasks[task_id]["task"]

        client = FailingAssessor()
        outcome = _driver(client, self.tmp).run({"project_id": "proj-2"}, _snapshot(self.tmp))
        self.assertEqual(outcome.status, "human-wait")
        self.assertNotIn("proj-2-synth", client.registered)

    def test_missing_artifact_never_passes(self):
        class NoArtifact(FakeAssessorClient):
            def read_shared_text(self, relative_path):
                raise HiclawError("no artifact")

        client = NoArtifact()
        outcome = _driver(client, self.tmp).run({"project_id": "proj-3"}, _snapshot(self.tmp))
        self.assertEqual(outcome.status, "human-wait")
        self.assertNotIn("proj-3-synth", client.registered)

    def test_run_creates_project_and_propagates_room_to_every_task(self):
        client = FakeAssessorClient()
        outcome = _driver(client, self.tmp).run(
            {"project_id": "proj-room", "run_id": "run-room",
             "title": "Room audit"},
            _snapshot(self.tmp),
        )

        self.assertEqual(outcome.status, "completed")
        self.assertEqual(client.events[0][0], "create_project")
        self.assertTrue(client.requests)
        self.assertEqual(
            {request["room_id"] for request in client.requests},
            {client.project_room_id},
        )
        publish_index = client.events.index(
            ("publish_shared_file", "projects/proj-room/snapshot.zip"))
        register_index = next(
            i for i, event in enumerate(client.events)
            if event[0] == "register_task")
        self.assertLess(publish_index, register_index)

    def test_run_stops_when_project_has_no_room(self):
        client = FakeAssessorClient()
        client.project_room_id = ""

        with self.assertRaisesRegex(
                HiclawError, "AgentTeams project has no Project Room"):
            _driver(client, self.tmp).run(
                {"project_id": "proj-no-room"}, _snapshot(self.tmp))

        self.assertFalse(client.registered)
        self.assertNotIn(
            "publish_shared_file", [event[0] for event in client.events])

    def test_run_rejects_snapshot_digest_mismatch_before_registration(self):
        client = FakeAssessorClient()
        snapshot = replace(_snapshot(self.tmp), archive_sha256="0" * 64)

        with self.assertRaisesRegex(HiclawError, "snapshot archive digest mismatch"):
            _driver(client, self.tmp).run(
                {"project_id": "proj-bad-snapshot"}, snapshot)

        self.assertFalse(client.registered)

    def test_register_task_uses_observed_skill_identity(self):
        client = FakeClient()
        driver = _driver(client, self.tmp)
        driver._register_task(
            "proj-x", "!proj-x:matrix.test", "proj-x-assessor-dep",
            "argus-dep", "assess", "argus-dependency-inspect",
            _snapshot(self.tmp), {})
        envelope = client.requests[0]
        # The Controller rejects task register unless skill_generation matches
        # the Worker's observed generation and skill_digest is a full sha256.
        self.assertEqual(envelope["skill_generation"], "g" * 64)
        self.assertEqual(envelope["skill_digest"], "sha256:" + "d" * 64)
        self.assertNotEqual(envelope["skill_digest"], "sha256:snap-1")
        self.assertEqual(envelope["room_id"], "!proj-x:matrix.test")


if __name__ == "__main__":
    unittest.main()
