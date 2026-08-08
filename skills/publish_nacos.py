#!/usr/bin/env python3
"""Publish and lock the eight Argus Skills into a local/private Nacos AI
Registry using the admin HTTP API with the Nacos server-identity header.

The private registry must reject overwriting an already published
`name + version`. The lock file is written only after every published version
fetches back and matches the local directory digest.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
LOCK_PATH = SKILLS_DIR / "skills.lock.json"

SKILLS = (
    "argus-dependency-inspect",
    "argus-code-rule-scan",
    "argus-secret-scan",
    "argus-ci-policy-check",
    "argus-finding-emit",
    "argus-evidence-verify",
    "argus-release-policy-evaluate",
    "argus-report-materialize",
)

ASSIGNMENTS = {
    "argus-dep": ["argus-dependency-inspect", "argus-finding-emit"],
    "argus-code": ["argus-code-rule-scan", "argus-finding-emit"],
    "argus-sec": ["argus-secret-scan", "argus-finding-emit"],
    "argus-delivery": ["argus-ci-policy-check", "argus-finding-emit"],
    "argus-meta": ["argus-evidence-verify"],
    "argus-synth": ["argus-release-policy-evaluate", "argus-report-materialize"],
}


class PublishError(RuntimeError):
    pass


_TEXT_SUFFIXES = {".json", ".md", ".py", ".txt", ".yaml", ".yml"}


def _digest(directory: Path) -> str:
    """LF-normalized directory digest, matching skill_directory_digest so the
    lock stays consistent across Windows checkouts."""
    digest = hashlib.sha256()
    sources = sorted(p for p in directory.rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix != ".pyc")
    for path in sources:
        rel = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        data = path.read_bytes()
        if path.suffix.lower() in _TEXT_SUFFIXES:
            data = data.replace(b"\r\n", b"\n")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def validate_skills() -> dict[str, str]:
    digests: dict[str, str] = {}
    for name in SKILLS:
        skill = SKILLS_DIR / name
        for required in ("SKILL.md", "manifest.yaml", "schemas/input.schema.json",
                         "schemas/output.schema.json", "implementation/main.py"):
            if not (skill / required).is_file():
                raise PublishError(f"skill {name} missing {required}")
        front = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        if not front.lstrip().startswith("---"):
            raise PublishError(f"skill {name} SKILL.md lacks YAML front matter")
        digests[name] = _digest(skill)
    return digests


def _build_archive(skill: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in skill.rglob("*") if p.is_file()
                           and "__pycache__" not in p.parts and p.suffix != ".pyc"):
            archive.writestr(path.relative_to(skill).as_posix(), path.read_bytes())
    return buffer.getvalue()


class NacosClient:
    def __init__(self, host: str, port: int, identity_key: str,
                 identity_value: str, namespace: str = "public"):
        self.base = f"http://{host}:{port}"
        self.v3_admin_base = f"{self.base}/nacos/v3/admin/ai/skills"
        self.v3_client_base = f"{self.base}/nacos/v3/client/ai/skills"
        self.identity = {identity_key: identity_value}
        self.namespace = namespace
        self.token = ""

    def login(self, username: str, password: str) -> None:
        form = urllib.parse.urlencode(
            {"username": username, "password": password}).encode()
        result = self._request("POST", "/v1/auth/login", form,
                               headers={"Content-Type": "application/x-www-form-urlencoded"},
                               raw_errors=True)
        token = result.get("accessToken")
        if not token:
            raise PublishError(f"nacos login failed: {result}")
        self.token = str(token)

    def _request(self, method: str, path: str, data=None,
                 headers: dict | None = None, raw_errors: bool = False) -> dict:
        url = path if path.startswith("http") else self.base + path
        request = urllib.request.Request(url, data=data, method=method)
        if self.token:
            # Token auth identifies the calling user for ownership checks.
            request.add_header("Authorization", "Bearer " + self.token)
        else:
            # Fall back to the server-identity header (admin bypass, no user).
            for key, value in self.identity.items():
                request.add_header(key, value)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if not raw_errors:
                raise PublishError(f"{method} {path} -> HTTP {exc.code}: {raw[:300]}")
            return {"code": exc.code, "message": raw[:300]}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"code": 0, "message": raw[:300]}

    def upload(self, name: str, version: str, zip_bytes: bytes) -> dict:
        boundary = f"argus-{int(time.time() * 1000)}"
        fields = {"namespaceId": self.namespace, "name": name, "version": version}
        body = io.BytesIO()
        for key, value in fields.items():
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.write(f"{value}\r\n".encode())
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="file"; '
                   f'filename="{name}.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode())
        body.write(zip_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        return self._request(
            "POST", self.v3_admin_base + "/upload", body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def submit(self, name: str) -> dict:
        # Submit the current editing draft; no version is assigned until release.
        form = urllib.parse.urlencode({
            "namespaceId": self.namespace, "skillName": name,
        }).encode()
        return self._request(
            "POST", self.v3_admin_base + "/submit", form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})

    def publish(self, name: str, version: str) -> dict:
        # Release assigns the immutable version to the approved reviewing draft.
        form = urllib.parse.urlencode({
            "namespaceId": self.namespace, "skillName": name, "version": version,
        }).encode()
        return self._request(
            "POST", self.v3_admin_base + "/publish", form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})

    def get_version_detail(self, name: str) -> dict | None:
        """Return the reviewing version detail with pipeline status."""
        result = self._request(
            "GET", self.v3_admin_base + "?skillName=" +
            urllib.parse.quote(name) + "&namespaceId=" + urllib.parse.quote(self.namespace))
        versions = (result.get("data") or {}).get("versions") or []
        for version in versions:
            if version.get("status") == "reviewed":
                return version
        return None

    def wait_approved(self, name: str, timeout_s: int = 60) -> str:
        """Poll the reviewing version until its publish pipeline is APPROVED.
        Returns the reviewing version string."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            detail = self.get_version_detail(name)
            if detail:
                pipeline = detail.get("publishPipelineInfo") or ""
                if '"status":"APPROVED"' in pipeline:
                    return str(detail["version"])
                if '"status":"REJECTED"' in pipeline:
                    raise PublishError(f"publish pipeline rejected for {name}")
            time.sleep(2)
        raise PublishError(f"publish pipeline not approved within {timeout_s}s for {name}")

    def fetch_skill(self, name: str, version: str) -> bytes:
        url = self.v3_client_base + "?" + urllib.parse.urlencode({
            "namespaceId": self.namespace, "name": name, "version": version,
        })
        request = urllib.request.Request(url, method="GET")
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        else:
            for key, value in self.identity.items():
                request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise PublishError(f"fetch {name}@{version} -> HTTP {exc.code}")


def publish_all(client: NacosClient, version: str, local_digests: dict[str, str]) -> dict[str, str]:
    """Upload, submit, wait for pipeline approval, and release each skill.
    Returns the actual released version strings per skill (Nacos assigns the
    first reviewing version, e.g. 0.0.1)."""
    released: dict[str, str] = {}
    for name in SKILLS:
        result = client.upload(name, version, _build_archive(SKILLS_DIR / name))
        if result.get("code") not in (0, 10000):
            raise PublishError(f"upload {name} failed: {result}")
    for name in SKILLS:
        submit = client.submit(name)
        if submit.get("code") not in (0, 10000):
            raise PublishError(f"submit {name} failed: {submit}")
    for name in SKILLS:
        actual_version = client.wait_approved(name)
        pub = client.publish(name, actual_version)
        if pub.get("code") not in (0, 10000):
            raise PublishError(f"publish {name}@{actual_version} failed: {pub}")
        released[name] = actual_version
        print(f"[publish_nacos] published {name}@{actual_version}")
    return released


def _strip_frontmatter_version(text: str) -> str:
    """Remove the Nacos-injected `version:` line from SKILL.md front matter so
    local and fetched content compare equal."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    body = []
    in_front = True
    for line in lines[1:]:
        if in_front and line.strip() == "---":
            in_front = False
            body.append(line)
            continue
        if in_front and line.strip().lower().startswith("version:"):
            continue
        body.append(line)
    return "".join(lines[:1] + body)


def _fetch_matches(local_skill: Path, zip_bytes: bytes, name: str) -> bool:
    """Fetch the skill ZIP and confirm every file matches local, except the
    Nacos-injected `version:` line in SKILL.md front matter."""
    import io as _io
    local_files = {
        p.relative_to(local_skill).as_posix(): p.read_bytes()
        for p in local_skill.rglob("*") if p.is_file()
        and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    with zipfile.ZipFile(_io.BytesIO(zip_bytes)) as archive:
        remote = {}
        for relative in archive.namelist():
            parts = relative.split("/", 1)
            if len(parts) == 1 or parts[0] != name:
                continue
            rel = parts[1]
            if rel.endswith(".pyc") or "__pycache__" in rel.split("/"):
                continue
            remote[rel] = archive.read(relative)
    if set(local_files) != set(remote):
        return False
    for rel in local_files:
        local_bytes = local_files[rel]
        remote_bytes = remote[rel]
        if rel == "SKILL.md":
            if _strip_frontmatter_version(
                    remote_bytes.decode("utf-8", errors="replace")) != \
               local_bytes.decode("utf-8", errors="replace"):
                return False
        elif local_bytes != remote_bytes:
            return False
    return True


def verify_all(client: NacosClient, versions: dict[str, str],
               local_digests: dict[str, str]) -> dict[str, str]:
    for name in SKILLS:
        data = client.fetch_skill(name, versions[name])
        if not _fetch_matches(SKILLS_DIR / name, data, name):
            raise PublishError(f"fetched skill does not match local: {name}")
    return local_digests


def write_lock(source: str, auth_type: str, versions: dict[str, str],
               observed: dict[str, str]) -> None:
    lock = {
        "schema_version": "2",
        "source": source,
        "auth_type": auth_type,
        "locked_at": datetime.now(timezone.utc).isoformat() + "Z",
        "skills": [
            {"name": name, "version": versions[name], "local_sha256": observed[name]}
            for name in SKILLS
        ],
        "assignments": ASSIGNMENTS,
    }
    LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("ARGUS_NACOS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARGUS_NACOS_PORT", "8848")))
    parser.add_argument("--namespace", default=os.environ.get("ARGUS_NACOS_NAMESPACE", "public"))
    parser.add_argument("--identity-key", default=os.environ.get("ARGUS_NACOS_IDENTITY_KEY", "serverIdentity"))
    parser.add_argument("--identity-value", default=os.environ.get("ARGUS_NACOS_IDENTITY_VALUE", "security"))
    parser.add_argument("--username", default=os.environ.get("ARGUS_NACOS_USERNAME", "nacos"))
    parser.add_argument("--password", default=os.environ.get("ARGUS_NACOS_PASSWORD", ""))
    parser.add_argument("--version", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify-only", action="store_true")
    group.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)

    client = NacosClient(args.host, args.port, args.identity_key,
                         args.identity_value, args.namespace)
    source = f"nacos://{args.host}:{args.port}/{args.namespace}"
    try:
        if args.username and args.password:
            client.login(args.username, args.password)
        local = validate_skills()
        if args.publish:
            versions = publish_all(client, args.version, local)
        else:
            versions = {name: args.version for name in SKILLS}
        observed = verify_all(client, versions, local)
        write_lock(source, "nacos", versions, observed)
    except (PublishError, OSError, TimeoutError) as exc:
        print(f"[publish_nacos] BLOCKED: {exc}", file=sys.stderr)
        return 4
    sample = sorted(set(versions.values()))
    print(f"[publish_nacos] verified {len(SKILLS)} skills at {source} "
          f"versions {sample}; lock written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
