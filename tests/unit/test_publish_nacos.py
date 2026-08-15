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
        self.submit_calls: list[str] = []
        self.publish_calls: list[tuple[str, str]] = []
        self.upload_calls: list[tuple[str, str, bytes]] = []
        self.wait_approved_calls: list[str] = []
        self._next_version = 1

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def fetch_skill(self, name: str, version: str) -> bytes:
        self.fetch_calls.append((name, version))
        if name not in self.archives:
            raise pn.PublishError(f"fetch {name}@{version} -> HTTP 404")
        return self.archives[name]

    def upload(self, name: str, version: str, zip_bytes: bytes) -> dict:
        self.upload_calls.append((name, version, zip_bytes))
        return {"code": 0}

    def submit(self, name: str) -> dict:
        self.submit_calls.append(name)
        return {"code": 0}

    def wait_approved(self, name: str) -> str:
        self.wait_approved_calls.append(name)
        self._next_version += 1
        return f"0.0.{self._next_version}"

    def publish(self, name: str, version: str) -> dict:
        self.publish_calls.append((name, version))
        return {"code": 0}


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

    def test_validate_skills_requires_nine_complete_packages(self):
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
        self.assertEqual(lock["source"], "nacos://nacos:secret@nacos:8848/argus")
        self.assertEqual(lock["auth_type"], "nacos")
        self.assertEqual(len(lock["skills"]), 9)
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


    def _existing_lock(self, version: str = "0.0.5") -> dict:
        local = pn.validate_skills()
        return {
            "schema_version": "2",
            "source": "nacos://nacos:nacos@nacos:8848/public",
            "auth_type": "nacos",
            "locked_at": "2026-08-10T17:37:46.033379+00:00Z",
            "skills": [{"name": name, "version": version,
                        "local_sha256": local[name]} for name in pn.SKILLS],
            "assignments": pn.ASSIGNMENTS,
        }

    def test_publish_reuses_locked_version_when_content_unchanged(self):
        local = pn.validate_skills()
        existing = self._existing_lock("0.0.5")
        client = _FakeNacosClient(self._matching_archives())

        released = pn.publish_all(client, "0.0.9", local, existing)

        # Every skill reused the locked version; no pipeline calls at all.
        self.assertEqual(released, {name: "0.0.5" for name in pn.SKILLS})
        self.assertEqual(client.submit_calls, [])
        self.assertEqual(client.publish_calls, [])
        self.assertEqual(client.upload_calls, [])
        self.assertEqual(
            sorted(client.fetch_calls),
            sorted((name, "0.0.5") for name in pn.SKILLS))

    def test_publish_bumps_only_changed_skill(self):
        local = pn.validate_skills()
        existing = self._existing_lock("0.0.5")
        # argus-secret-scan content changed locally → its locked digest no
        # longer matches, so it must be re-released.
        existing["skills"] = [
            item if item["name"] != "argus-secret-scan"
            else {**item, "local_sha256": "0" * 64}
            for item in existing["skills"]
        ]
        client = _FakeNacosClient(self._matching_archives())

        released = pn.publish_all(client, "0.0.9", local, existing)

        self.assertEqual(released["argus-secret-scan"], "0.0.2")
        self.assertEqual(client.submit_calls, ["argus-secret-scan"])
        self.assertEqual(client.publish_calls, [("argus-secret-scan", "0.0.2")])
        # Other skills reused without entering the pipeline.
        for name in pn.SKILLS:
            if name != "argus-secret-scan":
                self.assertEqual(released[name], "0.0.5")

    def test_publish_rereleases_when_locked_version_missing_in_nacos(self):
        local = pn.validate_skills()
        existing = self._existing_lock("0.0.5")
        archives = self._matching_archives()
        archives.pop("argus-finding-emit")  # Nacos no longer serves it
        client = _FakeNacosClient(archives)

        released = pn.publish_all(client, "0.0.9", local, existing)

        self.assertEqual(released["argus-finding-emit"], "0.0.2")
        self.assertIn("argus-finding-emit", client.submit_calls)
        self.assertIn("argus-finding-emit", client.wait_approved_calls)

    def test_publish_without_existing_lock_releases_every_skill(self):
        local = pn.validate_skills()
        client = _FakeNacosClient(self._matching_archives())

        released = pn.publish_all(client, "0.0.9", local, None)

        self.assertEqual(len(released), len(pn.SKILLS))
        self.assertEqual(set(client.submit_calls), set(pn.SKILLS))
        self.assertEqual(
            {name for name, _ in client.publish_calls}, set(pn.SKILLS))


if __name__ == "__main__":
    unittest.main()
