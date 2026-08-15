import json
import tempfile
import unittest
from pathlib import Path

from agentteams import hiclaw_client
from agentteams.hiclaw_client import HiclawClient, HiclawError
from agentteams.worker_payloads import WORKERS


class WorkerRemoteSkillApplyTests(unittest.TestCase):
    def test_observation_reads_target_worker_container(self):
        client = HiclawClient.__new__(HiclawClient)
        client.container = "agentteams-manager"
        calls = []

        def docker_exec_in(container, *args, **kwargs):
            calls.append((container, args))
            return '{"generation":"g1","skills":[]}'

        client._docker_exec_in = docker_exec_in

        observed = client.get_worker_skill_observation("argus-dep")

        self.assertEqual("g1", observed["generation"])
        self.assertEqual("agentteams-worker-argus-dep", calls[0][0])

    def test_apply_clears_legacy_builtin_skills(self):
        client = HiclawClient.__new__(HiclawClient)
        client.container = "unused"
        payloads = []

        def docker_exec(*args, **kwargs):
            if kwargs.get("input_text") is not None:
                payloads.append(kwargs["input_text"])
            return ""

        client._docker_exec = docker_exec
        client._run = lambda *args, **kwargs: ""

        client.apply_worker_remote_skills(
            "argus-dep", "deepseek-v4-flash", "openclaw", "",
            "nacos://nacos:8848/public", "nacos",
            {"argus-dependency-inspect": "0.0.1"},
        )

        self.assertEqual(1, len(payloads))
        self.assertIn("  skills: []\n", payloads[0])
        self.assertIn(
            "  image: agentteams/worker-agent:v1.2.0-beta.1-argus.7\n",
            payloads[0],
        )


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
                    "argus-example", "deepseek-v4-flash", "openclaw", "soul", [skill],
                    {"argus-example": "0" * 64},
                )

    def test_repository_skill_lock_matches_complete_artifacts(self):
        workspace = Path(__file__).resolve().parents[2]
        lock = json.loads(
            (workspace / "skills/skills.lock.json").read_text(encoding="utf-8"))

        self.assertEqual(len(lock["skills"]), 9)
        for item in lock["skills"]:
            actual = hiclaw_client.skill_directory_digest(
                workspace / "skills" / item["name"])
            self.assertEqual(item["local_sha256"], actual, item["name"])

    def test_worker_definitions_cover_all_lock_assignments(self):
        workspace = Path(__file__).resolve().parents[2]
        lock = json.loads(
            (workspace / "skills/skills.lock.json").read_text(encoding="utf-8"))
        for worker_name, expected_skills in lock["assignments"].items():
            worker = WORKERS.get(worker_name.split("-", 1)[1] if "-" in worker_name else worker_name)
            if worker is None:
                # Try matching by full name
                worker = next((w for w in WORKERS.values() if w.name == worker_name), None)
            self.assertIsNotNone(worker, f"no WORKERS entry for {worker_name}")
            self.assertEqual(set(expected_skills), set(worker.skills),
                             f"{worker_name} skill mismatch")


if __name__ == "__main__":
    unittest.main()
