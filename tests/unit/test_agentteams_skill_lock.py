import json
import tempfile
import unittest
from pathlib import Path

from agentteams import hiclaw_client
from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.orchestrator import Orchestrator, WORKERS


class RecordingWorkerClient:
    def __init__(self):
        self.packages = []

    def ensure_worker(self, name, model, runtime, *, soul):
        return {"name": name, "phase": "Running", "containerState": "running"}

    def ensure_ready(self, name, timeout_s):
        return True

    def apply_worker_package(self, name, model, runtime, soul, skill_dirs,
                             locked_digests):
        self.packages.append((name, locked_digests))

    def configure_worker(self, name, model, runtime, *, soul, skills):
        return None

    def get_workers(self, name):
        return [{"name": name, "phase": "Running", "containerState": "running"}]

    def read_worker_registry_entry(self, name):
        worker = next(worker for worker in WORKERS.values() if worker.name == name)
        return {"skills": list(worker.skills)}

    def worker_skill_exists(self, worker, skill):
        return True


class FinalStateWorkerClient(RecordingWorkerClient):
    def __init__(self):
        super().__init__()
        self.skill_checked = False

    def get_workers(self, name):
        phase = "Running" if self.skill_checked else "Starting"
        return [{"name": name, "phase": phase,
                 "containerState": phase.lower()}]

    def worker_skill_exists(self, worker, skill):
        self.skill_checked = True
        return True


class SkillDirectoryDigestTests(unittest.TestCase):
    def test_digest_is_line_ending_stable_and_covers_all_files(self):
        digest = getattr(hiclaw_client, "skill_directory_digest", None)
        self.assertIsNotNone(digest, "skill directory digest is not implemented")
        if digest is None:
            return

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lf = root / "lf"
            crlf = root / "crlf"
            for directory, newline in ((lf, "\n"), (crlf, "\r\n")):
                (directory / "implementation").mkdir(parents=True)
                (directory / "SKILL.md").write_bytes(
                    f"# Skill{newline}{newline}Rules{newline}".encode())
                (directory / "implementation/main.py").write_bytes(
                    f"def run():{newline}    return 1{newline}".encode())

            baseline = digest(lf)
            self.assertEqual(baseline, digest(crlf))

            cache = crlf / "implementation/__pycache__"
            cache.mkdir()
            (cache / "main.cpython-313.pyc").write_bytes(b"generated")
            self.assertEqual(baseline, digest(crlf))

            (crlf / "implementation/main.py").write_bytes(
                b"def run():\r\n    return 2\r\n")
            self.assertNotEqual(baseline, digest(crlf))

            binary_lf = root / "binary-lf"
            binary_crlf = root / "binary-crlf"
            binary_lf.mkdir()
            binary_crlf.mkdir()
            (binary_lf / "asset.bin").write_bytes(b"\x00\n\xff")
            (binary_crlf / "asset.bin").write_bytes(b"\x00\r\n\xff")
            self.assertNotEqual(digest(binary_lf), digest(binary_crlf))

    def test_package_rejects_skill_when_lock_digest_does_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "argus-example"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
            client = HiclawClient.__new__(HiclawClient)
            client.container = "unused"

            with self.assertRaisesRegex(HiclawError, "digest mismatch"):
                client.apply_worker_package(
                    "argus-example", "model", "openclaw", "soul", [skill],
                    {"argus-example": "0" * 64},
                )

    def test_repository_skill_lock_matches_complete_artifacts(self):
        workspace = Path(__file__).resolve().parents[2]
        lock = json.loads(
            (workspace / "skills/skills.lock.json").read_text(encoding="utf-8"))

        for item in lock["skills"]:
            actual = hiclaw_client.skill_directory_digest(
                workspace / "skills" / item["name"])
            self.assertEqual(item["sha256"], actual, item["name"])

    def test_orchestrator_observes_final_running_state_after_skill_materialization(self):
        workspace = Path(__file__).resolve().parents[2]
        client = FinalStateWorkerClient()

        states = Orchestrator(client, workspace).ensure_core_workers(timeout_s=1)

        self.assertTrue(states)
        self.assertTrue(all(state["phase"] == "Running" for state in states))

    def test_orchestrator_supplies_locked_digests_for_every_worker_package(self):
        workspace = Path(__file__).resolve().parents[2]
        client = RecordingWorkerClient()

        Orchestrator(client, workspace).ensure_core_workers(timeout_s=1)

        self.assertEqual(len(WORKERS), len(client.packages))
        for worker_name, locked_digests in client.packages:
            worker = next(worker for worker in WORKERS.values()
                          if worker.name == worker_name)
            self.assertEqual(set(worker.skills), set(locked_digests))
            self.assertTrue(all(len(value) == 64
                                for value in locked_digests.values()))


if __name__ == "__main__":
    unittest.main()
