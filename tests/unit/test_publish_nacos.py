"""Unit tests for the HTTP-based Nacos Skill publisher."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import skills.publish_nacos as pn


class _FakeNacosClient:
    def __init__(self, archives: dict[str, bytes]):
        self.archives = archives
        self.login_calls: list[tuple[str, str]] = []
        self.fetch_calls: list[tuple[str, str]] = []

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def fetch_skill(self, name: str, version: str) -> bytes:
        self.fetch_calls.append((name, version))
        return self.archives[name]


def _nacos_archive(name: str, *, mutate: str | None = None) -> bytes:
    """Build the prefixed ZIP shape returned by the Nacos client endpoint."""
    skill = pn.SKILLS_DIR / name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in skill.rglob("*") if p.is_file()
                           and "__pycache__" not in p.parts and p.suffix != ".pyc"):
            relative = path.relative_to(skill).as_posix()
            data = path.read_bytes()
            if relative == "SKILL.md":
                text = data.decode("utf-8")
                text = text.replace("---\n", "---\nversion: 0.0.1\n", 1)
                data = text.encode("utf-8")
            if relative == mutate:
                data += b"\nchanged"
            archive.writestr(f"{name}/{relative}", data)
    return buffer.getvalue()


class PublishNacosTest(unittest.TestCase):
    def setUp(self):
        pn.ROOT = Path(__file__).resolve().parents[2]
        pn.SKILLS_DIR = pn.ROOT / "skills"
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        pn.LOCK_PATH = Path(temp_dir.name) / "skills.lock.json"

    def _matching_archives(self) -> dict[str, bytes]:
        return {name: _nacos_archive(name) for name in pn.SKILLS}

    def test_validate_skills_requires_eight_complete_packages(self):
        digests = pn.validate_skills()

        self.assertEqual(set(digests), set(pn.SKILLS))
        for name in pn.SKILLS:
            self.assertEqual(len(digests[name]), 64)

    def test_login_rejects_response_without_access_token(self):
        client = pn.NacosClient("localhost", 8848, "serverIdentity", "security")

        with mock.patch.object(client, "_request", return_value={"code": 403}):
            with self.assertRaisesRegex(pn.PublishError, "login failed"):
                client.login("nacos", "wrong-password")

        self.assertEqual(client.token, "")

    def test_verify_all_accepts_matching_http_archives_and_versions(self):
        local = pn.validate_skills()
        versions = {name: f"0.0.{index + 1}" for index, name in enumerate(pn.SKILLS)}
        client = _FakeNacosClient(self._matching_archives())

        observed = pn.verify_all(client, versions, local)

        self.assertEqual(observed, local)
        self.assertEqual(client.fetch_calls,
                         [(name, versions[name]) for name in pn.SKILLS])

    def test_verify_all_rejects_mismatched_http_archive(self):
        local = pn.validate_skills()
        versions = {name: "0.0.1" for name in pn.SKILLS}
        archives = self._matching_archives()
        archives["argus-secret-scan"] = _nacos_archive(
            "argus-secret-scan", mutate="implementation/main.py")
        client = _FakeNacosClient(archives)

        with self.assertRaisesRegex(
                pn.PublishError, "fetched skill does not match local: argus-secret-scan"):
            pn.verify_all(client, versions, local)

    def test_verify_only_writes_lock_after_all_http_archives_match(self):
        client = _FakeNacosClient(self._matching_archives())
        with mock.patch.object(pn, "NacosClient", return_value=client):
            result = pn.main([
                "--host", "private-nacos",
                "--namespace", "argus",
                "--username", "nacos",
                "--password", "secret",
                "--version", "0.0.1",
                "--verify-only",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(client.login_calls, [("nacos", "secret")])
        lock = json.loads(pn.LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], "2")
        self.assertEqual(lock["source"], "nacos://private-nacos:8848/argus")
        self.assertEqual(lock["auth_type"], "nacos")
        self.assertEqual(len(lock["skills"]), 8)
        self.assertEqual(len(lock["assignments"]), 6)
        self.assertTrue(all(item["version"] == "0.0.1" for item in lock["skills"]))

    def test_verify_only_does_not_write_lock_when_one_archive_mismatches(self):
        archives = self._matching_archives()
        archives["argus-secret-scan"] = _nacos_archive(
            "argus-secret-scan", mutate="implementation/main.py")
        client = _FakeNacosClient(archives)
        with mock.patch.object(pn, "NacosClient", return_value=client):
            result = pn.main([
                "--host", "private-nacos",
                "--version", "0.0.1",
                "--verify-only",
            ])

        self.assertEqual(result, 4)
        self.assertFalse(pn.LOCK_PATH.exists())


if __name__ == "__main__":
    unittest.main()
