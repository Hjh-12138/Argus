"""Typed wrapper around the pinned AgentTeams control-plane interfaces.

Worker lifecycle always goes through ``hiclaw``. Project, Matrix, MinIO, and
Skill operations use the Manager's versioned built-in scripts because
AgentTeams v1.2.0-beta.1 does not expose those resources through hiclaw.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


class HiclawError(Exception):
    pass


_TEXT_SKILL_SUFFIXES = {".json", ".md", ".py", ".txt", ".yaml", ".yml"}


def _skill_artifact_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    if path.suffix.lower() in _TEXT_SKILL_SUFFIXES:
        return content.replace(b"\r\n", b"\n")
    return content


def skill_directory_digest(directory: Path) -> str:
    """Hash every Skill artifact using stable paths and canonical text bytes."""
    root = Path(directory).resolve()
    digest = hashlib.sha256()
    sources = (path for path in root.rglob("*") if path.is_file()
               and "__pycache__" not in path.parts and path.suffix != ".pyc")
    for source in sorted(sources):
        relative = source.relative_to(root).as_posix().encode("utf-8")
        content = _skill_artifact_bytes(source)
        digest.update(relative)
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


class HiclawClient:
    PROJECT_SCRIPT = "/opt/hiclaw/agent/skills/project-management/scripts/create-project.sh"
    SHARED_ROOT = PurePosixPath("/root/hiclaw-fs/shared")
    STORAGE_ROOT = "agentteams/agentteams-storage/shared"
    ARGUS_WORKER_IMAGE = "agentteams/worker-agent:v1.2.0-beta.1-argus.7"

    def __init__(self, container: str | None = None):
        self.container = container or self._detect_manager_container()

    @staticmethod
    def _detect_manager_container() -> str:
        probe = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        if probe.returncode == 0:
            names = set(probe.stdout.splitlines())
            for candidate in ("agentteams-manager", "hiclaw-manager"):
                if candidate in names:
                    return candidate
        return "agentteams-manager"

    def _docker_exec_in(self, container: str, *args: str, timeout: int = 60,
                        input_text: str | None = None) -> str:
        command = ["docker", "exec"]
        if input_text is not None:
            command.append("-i")
        command.extend([container, *args])
        try:
            proc = subprocess.run(
                command, input=input_text, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HiclawError(f"docker exec failed: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise HiclawError(f"{' '.join(args)} failed in {container}: {detail}")
        return proc.stdout.strip()

    def _docker_exec(self, *args: str, timeout: int = 60,
                     input_text: str | None = None) -> str:
        return self._docker_exec_in(
            self.container, *args, timeout=timeout, input_text=input_text)

    def _run(self, *args: str, timeout: int = 60) -> str:
        return self._docker_exec("hiclaw", *args, timeout=timeout)

    @staticmethod
    def _json_output(raw: str, context: str) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HiclawError(f"{context} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise HiclawError(f"{context} returned unexpected JSON")
        return data

    def get_workers(self, name: str | None = None) -> list[dict]:
        args = ["get", "workers"]
        if name:
            args.append(name)
        args.extend(["-o", "json"])
        data = self._json_output(self._run(*args), "hiclaw get workers")
        if "workers" in data and isinstance(data["workers"], list):
            return list(data["workers"])
        if "name" in data:
            return [data]
        raise HiclawError("unexpected hiclaw worker response")

    def create_worker(self, name: str, model: str, runtime: str = "openclaw",
                      *, soul: str = "", skills: Iterable[str] = (),
                      no_wait: bool = True) -> dict:
        args = ["create", "worker", "--name", name, "--model", model,
                "--runtime", runtime]
        if soul:
            args.extend(["--soul", soul])
        skill_names = sorted(set(skills))
        if skill_names:
            args.extend(["--skills", ",".join(skill_names)])
        if no_wait:
            args.append("--no-wait")
        args.extend(["-o", "json"])
        return self._json_output(
            self._run(*args, timeout=180), f"hiclaw create worker {name}")

    def ensure_worker(self, name: str, model: str, runtime: str = "openclaw",
                      *, soul: str = "", skills: Iterable[str] = ()) -> dict:
        current = self.get_workers()
        found = next((w for w in current if w.get("name") == name), None)
        return found or self.create_worker(
            name, model, runtime, soul=soul, skills=skills, no_wait=True)

    def configure_worker(self, name: str, model: str,
                         runtime: str = "openclaw", *, soul: str = "",
                         skills: Iterable[str] = ()) -> None:
        args = ["apply", "worker", "--name", name, "--model", model,
                "--runtime", runtime]
        if soul:
            args.extend(["--soul", soul])
        skill_names = sorted(set(skills))
        if skill_names:
            args.extend(["--skills", ",".join(skill_names)])
        self._run(*args, timeout=180)

    def ensure_ready(self, name: str, timeout_s: int = 300) -> bool:
        self._run("worker", "ensure-ready", "--name", name, timeout=60)
        return self.wait_ready(name, timeout_s)

    def wait_ready(self, name: str, timeout_s: int = 300) -> bool:
        import time
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            workers = self.get_workers(name)
            if workers:
                phase = workers[0].get("phase")
                if phase in ("Ready", "Running"):
                    return True
                if phase == "Failed":
                    raise HiclawError(
                        f"worker {name} failed: {workers[0].get('message', 'unknown error')}")
            time.sleep(5)
        return False

    def apply_worker_package(self, name: str, model: str, runtime: str,
                             soul: str, skill_dirs: Iterable[Path],
                             locked_digests: dict[str, str]) -> None:
        """Publish locked Skills through AgentTeams' controller-owned ZIP path."""
        self._validate_id(name, "worker")
        skill_paths = [Path(p).resolve() for p in skill_dirs]
        for path in skill_paths:
            if (not (path / "SKILL.md").is_file()
                    or not re.fullmatch(r"argus-[a-z0-9-]+", path.name)):
                raise HiclawError(f"invalid skill directory: {path}")
            expected = locked_digests.get(path.name)
            actual = skill_directory_digest(path)
            if expected != actual:
                raise HiclawError(
                    f"Skill digest mismatch for {path.name}: "
                    f"expected {expected or 'missing'}, got {actual}")
        with tempfile.TemporaryDirectory(prefix="argus-worker-package-") as tmp:
            package = Path(tmp) / "package"
            (package / "config").mkdir(parents=True)
            (package / "config/SOUL.md").write_text(soul, encoding="utf-8")
            manifest = {
                "type": "worker", "version": 1,
                "worker": {"suggested_name": name, "model": model,
                           "runtime": runtime},
                "source": {"hostname": "argus", "locked_skills": True},
            }
            (package / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            zip_path = Path(tmp) / f"{name}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(package / "manifest.json", "manifest.json")
                archive.write(package / "config/SOUL.md", "config/SOUL.md")
                for skill in skill_paths:
                    sources = (path for path in skill.rglob("*") if path.is_file()
                               and "__pycache__" not in path.parts
                               and path.suffix != ".pyc")
                    for source in sorted(sources):
                        relative = source.relative_to(skill).as_posix()
                        archive.writestr(
                            f"skills/{skill.name}/{relative}",
                            _skill_artifact_bytes(source),
                        )
            container_zip = f"/tmp/{name}-argus-skills.zip"
            copied = subprocess.run(
                ["docker", "cp", str(zip_path),
                 f"{self.container}:{container_zip}"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
            )
            if copied.returncode != 0:
                raise HiclawError(
                    f"failed to stage worker package: "
                    f"{(copied.stderr or copied.stdout).strip()}")
            try:
                self._run(
                    "apply", "worker", "--name", name, "--zip", container_zip,
                    "--runtime", runtime, timeout=180,
                )
            finally:
                self._docker_exec("rm", "-f", container_zip, timeout=30)

    # ------------------------------------------------------------------
    # Typed Task protocol (v1) against the fork controller.
    # ------------------------------------------------------------------

    def register_task(self, request: dict) -> dict:
        import time
        payload = json.dumps(request, ensure_ascii=False)
        path = f"/tmp/argus-task-{int(time.time() * 1000)}.json"
        self._docker_exec(
            "sh", "-c", "cat > \"$1\"", "argus-task-write", path,
            input_text=payload, timeout=30,
        )
        try:
            raw = self._run("task", "register", "--file", path, "-o", "json",
                            timeout=60)
            return self._json_output(raw, "task register")
        finally:
            try:
                self._docker_exec("rm", "-f", path, timeout=15)
            except HiclawError:
                pass

    def get_task(self, task_id: str) -> dict:
        self._validate_id(task_id, "task")
        raw = self._run("task", "get", "--id", task_id, "-o", "json", timeout=60)
        return self._json_output(raw, "task get")

    def dispatch_task(self, task_id: str, revision: int) -> dict:
        self._validate_id(task_id, "task")
        raw = self._run("task", "dispatch", "--id", task_id,
                        "--revision", str(revision), "-o", "json", timeout=60)
        return self._json_output(raw, "task dispatch")

    def ack_task(self, task_id: str, revision: int) -> dict:
        self._validate_id(task_id, "task")
        raw = self._run("task", "ack", "--id", task_id,
                        "--revision", str(revision), "-o", "json", timeout=60)
        return self._json_output(raw, "task ack")

    def start_task(self, task_id: str, revision: int) -> dict:
        self._validate_id(task_id, "task")
        raw = self._run("task", "start", "--id", task_id,
                        "--revision", str(revision), "-o", "json", timeout=60)
        return self._json_output(raw, "task start")

    def terminal_task(self, task_id: str, revision: int, state: str,
                      code: str) -> dict:
        self._validate_id(task_id, "task")
        raw = self._run("task", "terminal", "--id", task_id,
                        "--revision", str(revision), "--state", state,
                        "--code", code, "-o", "json", timeout=60)
        return self._json_output(raw, "task terminal")

    def wait_task(self, task_id: str, terminal: set[str],
                  timeout_s: int = 300) -> dict:
        import time
        self._validate_id(task_id, "task")
        deadline = time.monotonic() + timeout_s
        delays = (2, 4, 8, 15, 30)  # exponential backoff, cap at 30s
        step = 0
        while time.monotonic() < deadline:
            record = self.get_task(task_id)["task"]
            if record.get("state") in terminal:
                return record
            delay = delays[min(step, len(delays) - 1)]
            time.sleep(delay)
            step += 1
        raise HiclawError(f"task {task_id} did not reach terminal state")

    def stop_mirror(self) -> None:
        """Pause the mc-mirror background sync during heavy I/O operations."""
        try:
            self._docker_exec(
                "supervisorctl", "stop", "mc-mirror", timeout=30)
        except HiclawError:
            pass  # already stopped or supervisorctl not available

    def start_mirror(self) -> None:
        """Resume the mc-mirror background sync."""
        try:
            self._docker_exec(
                "supervisorctl", "start", "mc-mirror", timeout=30)
        except HiclawError:
            pass

    def get_worker_skill_observation(self, worker: str) -> dict:
        """Read the Worker's observed remote-Skill generation state."""
        self._validate_id(worker, "worker")
        container = f"agentteams-worker-{worker}"
        try:
            raw = self._docker_exec_in(
                container, "sh", "-c",
                "[ -f /root/hiclaw-fs/agents/$1/.skills/observed.json ] && "
                "cat /root/hiclaw-fs/agents/$1/.skills/observed.json || echo {}",
                "argus-observed", worker, timeout=30,
            )
        except HiclawError:
            return {}
        try:
            return self._json_output(raw, "worker skill observation")
        except HiclawError:
            return {}

    def get_worker_effective_model(self, name: str) -> str | None:
        """Read the desired model field exposed by the pinned Worker API."""
        workers = self.get_workers(name)
        if not workers:
            return None
        record = workers[0]
        for key in ("model", "effectiveModel"):
            value = record.get(key)
            if isinstance(value, str):
                return value
        spec = record.get("spec")
        if isinstance(spec, dict) and isinstance(spec.get("model"), str):
            return spec["model"]
        return None

    def worker_configuration(self, name: str) -> dict:
        """Return sanitized Worker state for preflight diagnostics."""
        workers = self.get_workers(name)
        if not workers:
            return {"name": name, "phase": "missing", "model": None,
                    "runtime": None, "image": None, "skills": []}
        record = workers[0]
        skills = self.get_worker_skill_observation(name)
        ready = sorted({item.get("name") for item in skills.get("skills", [])
                        if item.get("ready") and isinstance(item.get("name"), str)})
        return {
            "name": record.get("name", name),
            "phase": record.get("phase"),
            "model": self.get_worker_effective_model(name),
            "runtime": record.get("runtime"),
            "image": record.get("image"),
            "skills": ready,
        }

    def apply_worker_remote_skills(self, name: str, model: str,
                                   runtime: str, soul: str,
                                   source: str, auth_type: str,
                                   skill_versions: dict[str, str]) -> None:
        """Apply a Worker CR that declares remoteSkills from the lock.

        Custom Argus Skills never travel through the built-in `--skills` flag.
        Versions are read from the lock file — publish_nacos.py auto-updates
        the lock after every publish, so no manual version management.
        """
        from agentteams.model_config import validate_model

        self._validate_id(name, "worker")
        model = validate_model(model)
        yaml_lines = [
            "apiVersion: agentteams.io/v1beta1",
            "kind: Worker",
            "metadata:",
            f"  name: {name}",
            "spec:",
            f"  model: {model}",
            f"  runtime: {runtime}",
            f"  image: {self.ARGUS_WORKER_IMAGE}",
            "  skills: []",
            "  remoteSkills:",
            "    - source: " + source,
            f"      authType: {auth_type}",
            "      skills:",
        ]
        for skill_name in sorted(skill_versions):
            yaml_lines.append(f"        - name: {skill_name}")
            yaml_lines.append(f"          version: {skill_versions[skill_name]}")
        if soul:
            yaml_lines.append("  soul: |")
            for line in soul.splitlines():
                yaml_lines.append("    " + line)
        yaml_text = "\n".join(yaml_lines) + "\n"
        import time
        path = f"/tmp/argus-worker-{int(time.time() * 1000)}.yaml"
        self._docker_exec(
            "sh", "-c", "cat > \"$1\"", "argus-worker-write", path,
            input_text=yaml_text, timeout=30,
        )
        try:
            self._run("apply", "--file", path, timeout=180)
        finally:
            try:
                self._docker_exec("rm", "-f", path, timeout=15)
            except HiclawError:
                pass

    def create_project(self, project_id: str, title: str,
                       workers: Iterable[str]) -> dict:
        self._validate_id(project_id, "project")
        worker_names = tuple(dict.fromkeys(workers))
        if not worker_names:
            raise HiclawError("project requires at least one worker")
        for worker in worker_names:
            self._validate_id(worker, "worker")
        raw = self._docker_exec(
            "bash", self.PROJECT_SCRIPT,
            "--id", project_id, "--title", title,
            "--workers", ",".join(worker_names), timeout=180,
        )
        marker = "---RESULT---"
        if marker not in raw:
            raise HiclawError("create-project.sh returned no result marker")
        return self._json_output(raw.rsplit(marker, 1)[1].strip(), "create project")

    def write_shared_text(self, relative_path: str, content: str) -> None:
        relative = self._shared_relative(relative_path)
        target = self.SHARED_ROOT / relative
        script = (
            "set -eu; target=\"$1\"; mkdir -p \"$(dirname \"$target\")\"; "
            "umask 077; cat > \"$target\""
        )
        self._docker_exec(
            "sh", "-c", script, "argus-write", str(target),
            input_text=content, timeout=60,
        )

    def publish_shared_text(self, relative_path: str, content: str) -> None:
        """Publish exact content to MinIO and the Manager mirror.

        Project creation has a background mirror that can race with a local
        rewrite. Publishing from a private temporary file makes the MinIO
        object authoritative before updating the shared local mirror.
        """
        relative = self._shared_relative(relative_path)
        local = self.SHARED_ROOT / relative
        remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}"
        script = r'''
set -eu
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"
mc cp "$tmp" "$2" >/dev/null
mkdir -p "$(dirname "$1")"
cp "$tmp" "$1"
'''.strip()
        self._docker_exec(
            "sh", "-c", script, "argus-publish", str(local), remote,
            input_text=content, timeout=60,
        )

    def publish_shared_file(self, relative_path: str,
                            source_path: Path) -> None:
        """Publish exact binary bytes to MinIO and the Manager mirror."""
        relative = self._shared_relative(relative_path)
        source = Path(source_path).resolve()
        if not source.is_file():
            raise HiclawError(f"shared source file does not exist: {source}")
        local = self.SHARED_ROOT / relative
        remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}"
        encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        script = r'''
set -eu
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
base64 -d > "$tmp"
mc cp "$tmp" "$2" >/dev/null
mkdir -p "$(dirname "$1")"
cp "$tmp" "$1"
'''.strip()
        self._docker_exec(
            "sh", "-c", script, "argus-publish-file", str(local), remote,
            input_text=encoded, timeout=120,
        )

    def read_shared_text(self, relative_path: str, *, refresh: bool = False) -> str:
        relative = self._shared_relative(relative_path)
        local = self.SHARED_ROOT / relative
        if refresh:
            remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}"
            self._docker_exec("mc", "cp", remote, str(local), timeout=60)
        return self._docker_exec("cat", str(local), timeout=60)

    def shared_exists(self, relative_path: str, *, refresh: bool = False) -> bool:
        relative = self._shared_relative(relative_path)
        local = self.SHARED_ROOT / relative
        if refresh:
            remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}"
            try:
                self._docker_exec("mc", "stat", remote, timeout=30)
                return True
            except HiclawError:
                return False
        proc = subprocess.run(
            ["docker", "exec", self.container, "test", "-e", str(local)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        return proc.returncode == 0

    def sync_shared_directory(self, relative_path: str) -> None:
        relative = self._shared_relative(relative_path)
        local = f"{self.SHARED_ROOT / relative}/"
        remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}/"
        self._docker_exec("mc", "mirror", local, remote, "--overwrite", timeout=120)

    def pull_shared_directory(self, relative_path: str) -> None:
        relative = self._shared_relative(relative_path)
        local = f"{self.SHARED_ROOT / relative}/"
        remote = f"{self.STORAGE_ROOT}/{relative.as_posix()}/"
        self._docker_exec("mkdir", "-p", local)
        self._docker_exec("mc", "mirror", remote, local, "--overwrite", timeout=120)

    def send_project_message(self, room_id: str, body: str,
                             mentions: Iterable[str] = ()) -> None:
        encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
        mention_json = json.dumps(list(mentions), ensure_ascii=True)
        script = r'''
set -eu
[ -f /opt/hiclaw/scripts/lib/hiclaw-env.sh ] && . /opt/hiclaw/scripts/lib/hiclaw-env.sh
[ -f /data/hiclaw-secrets.env ] && . /data/hiclaw-secrets.env
if [ -z "${MANAGER_MATRIX_TOKEN:-}" ]; then
  MANAGER_MATRIX_TOKEN=$(curl -fsS -X POST "${AGENTTEAMS_MATRIX_URL}/_matrix/client/v3/login" \
    -H 'Content-Type: application/json' \
    -d '{"type":"m.login.password","identifier":{"type":"m.id.user","user":"manager"},"password":"'"${AGENTTEAMS_MANAGER_PASSWORD}"'"}' \
    | jq -r '.access_token // empty')
fi
: "${MANAGER_MATRIX_TOKEN:?manager Matrix token unavailable}"
body=$(printf '%s' "$2" | base64 -d)
txn="argus-$(date +%s%N)"
payload=$(jq -n --arg body "$body" --argjson mentions "$3" \
  '{msgtype:"m.text",body:$body,"m.mentions":{user_ids:$mentions}}')
curl -fsS -X PUT \
  "${AGENTTEAMS_MATRIX_URL}/_matrix/client/v3/rooms/$1/send/m.room.message/${txn}" \
  -H "Authorization: Bearer ${MANAGER_MATRIX_TOKEN}" \
  -H 'Content-Type: application/json' -d "$payload" >/dev/null
'''.strip()
        self._docker_exec(
            "bash", "-c", script, "argus-message", room_id, encoded,
            mention_json, timeout=60,
        )

    def send_admin_dm(self, room_id: str, body: str,
                      mentions: Iterable[str] = ()) -> None:
        """Send a Matrix DM as @admin to the Manager Agent.

        The Manager ignores messages from itself, so audit requests must
        arrive from a different user. This method authenticates as @admin
        using the AGENTTEAMS_ADMIN_PASSWORD env var on the controller.
        """
        admin_password = self._docker_exec_in(
            "agentteams-controller",
            "sh", "-c", "echo \"$AGENTTEAMS_ADMIN_PASSWORD\"")
        admin_password = admin_password.strip()
        if not admin_password:
            raise HiclawError(
                "AGENTTEAMS_ADMIN_PASSWORD not set on controller container")

        encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
        mention_json = json.dumps(list(mentions), ensure_ascii=True)
        homeserver = "http://agentteams-controller:6167"

        script = r'''
set -eu
body=$(printf '%s' "$1" | base64 -d)
txn="argus-admin-$(date +%s%N)"
token=$(curl -fsS -X POST "$2/_matrix/client/v3/login" \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","identifier":{"type":"m.id.user","user":"admin"},"password":"'"$3"'"}' \
  | jq -r '.access_token // empty')
: "${token:?admin Matrix login failed}"
payload=$(jq -n --arg body "$body" --argjson mentions "$4" \
  '{msgtype:"m.text",body:$body,"m.mentions":{user_ids:$mentions}}')
curl -fsS -X PUT \
  "$2/_matrix/client/v3/rooms/$5/send/m.room.message/${txn}" \
  -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/json' -d "$payload" >/dev/null
'''.strip()
        self._docker_exec(
            "bash", "-c", script, "argus-admin-dm",
            encoded, homeserver, admin_password, mention_json, room_id,
            timeout=60,
        )

    @staticmethod
    def _validate_id(value: str, kind: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,127}", value):
            raise HiclawError(f"invalid {kind} id: {value!r}")

    @staticmethod
    def _shared_relative(value: str) -> PurePosixPath:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise HiclawError(f"unsafe shared path: {value!r}")
        if path.parts[0] not in ("projects", "tasks"):
            raise HiclawError("shared path must be under projects/ or tasks/")
        return path
