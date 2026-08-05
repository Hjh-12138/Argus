# AgentTeams-Native Typed Task Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Argus typed tasks execute through AgentTeams v1.2.0-beta.1's Project Room, structured Matrix mention, OpenClaw current-message routing, and existing `hiclaw task execute` path, with the real snapshot archive published before dispatch.

**Architecture:** Argus creates one AgentTeams Project for the six participating Workers and writes its `project_room_id` into every typed-task envelope. Controller dispatch remains unchanged and emits `ARGUS_TYPED_TASK` with a full Matrix `m.mentions` target; OpenClaw routes that current message to the existing `typed-task-execution` Skill. Argus publishes `snapshot.zip` as binary-safe shared storage before registration and continues to use Controller task state and artifacts as the machine source of truth.

**Tech Stack:** Python 3, `unittest`/pytest, Docker CLI, MinIO `mc`, Bash, Matrix Client API, Go controller tests, OpenClaw Worker runtime.

## Global Constraints

- Preserve AgentTeams Project Room + Matrix `m.mentions` + OpenClaw current-message execution. Do not add a task-list API, Worker queue poller, or MinIO task scanner.
- Do not modify or stage `E:/heishou/AgentTeams-v1.2.0-beta.1/install/hiclaw-install.ps1`; it contains intentional pre-existing changes.
- Do not modify Koubo. A4 must audit `E:/heishou/koubo` read-only.
- Do not add Docker ServiceAccount token rotation unless restored live execution proves a 401 on a fresh Worker or an age-correlated expiry.
- Stage exact files only. Never use `git add -A` in either dirty repository.
- AgentTeams image-content changelog policy does not apply to the planned fork change because only `tests/test-task-worker-execution.sh` changes; if implementation expands into `worker/`, `manager/`, or `hiclaw-controller/`, add a separate approved task and update `changelog/current.md`.
- Preserve existing Controller task transitions, revision checks, ownership checks, idempotency key calculation, Skill identity checks, and bounded public errors.

---

## File Map

### Argus repository

- Modify `agentteams/worker_payloads.py`: carry the local snapshot archive path in `SnapshotReference`.
- Modify `cli/argus.py`: populate `SnapshotReference.archive_path` from the archive built for the current run.
- Modify `agentteams/hiclaw_client.py`: add binary-safe `publish_shared_file(relative_path, source_path)` using base64 transport into a private Manager-container temporary file, remote-first MinIO publication, then local mirror update.
- Modify `agentteams/project_driver.py`: create the AgentTeams Project, require `project_room_id`, publish and verify `snapshot.zip`, and pass the room ID to every typed task.
- Modify `tests/unit/test_project_driver.py`: prove project-before-task ordering, room propagation, snapshot-before-register ordering, and fail-closed behavior.
- Create `tests/unit/test_hiclaw_client_shared_file.py`: prove byte preservation, path validation, and remote-first publication command construction.
- Keep `docs/superpowers/specs/2026-08-05-agentteams-native-typed-task-design.md` as the approved design source.

### AgentTeams fork

- Modify `tests/test-task-worker-execution.sh`: replace the current false-positive scaffold with a real Project Room/Matrix/OpenClaw/typed-task execution test.
- Reuse without modification:
  - `manager/agent/skills/project-management/scripts/create-project.sh`
  - `hiclaw-controller/internal/server/task_handler.go`
  - `manager/agent/worker-agent/AGENTS.md`
  - `manager/agent/worker-agent/skills/typed-task-execution/SKILL.md`
  - `hiclaw-controller/cmd/hiclaw/task_cmd.go`
  - `tests/fixtures/deterministic-skill/`
  - `tests/lib/test-helpers.sh`, `tests/lib/matrix-client.sh`, and `tests/lib/minio-client.sh`

---

### Task 1: Carry the snapshot archive path through the typed-task boundary

**Files:**
- Modify: `agentteams/worker_payloads.py:20-25`
- Modify: `cli/argus.py:213-223`
- Modify: `tests/unit/test_project_driver.py:142-146`
- Test: `tests/unit/test_agentteams_cli_state.py:19-31`

**Interfaces:**
- Produces: `SnapshotReference.archive_path: str`, an absolute or caller-resolved local path to the immutable ZIP built for this audit.
- Consumes: `WorkspaceSnapshotBuilder.build(target, archive)` and the existing `archive` path in `_audit_agentteams`.

- [ ] **Step 1: Write the failing dataclass and CLI boundary tests**

Update the `_snapshot()` fixture in `tests/unit/test_project_driver.py` to create actual archive bytes and use their digest:

```python
def _snapshot(tmp: Path) -> SnapshotReference:
    archive = tmp / "snapshot.zip"
    archive.write_bytes(b"PK\x03\x04typed-task-snapshot")
    return SnapshotReference(
        snapshot_id="snap-1",
        source_root="/root/hiclaw-fs/shared",
        files=({"path": "app.py", "sha256": "0" * 64,
                "size": 10, "language": "py"},),
        archive_path=str(archive),
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
```

Add a focused assertion to `tests/unit/test_agentteams_cli_state.py` by recording the `snapshot` passed to `_FakeDriver.run`:

```python
class _FakeDriver:
    last_snapshot = None

    def run(self, request, snapshot, profile="", acceptance_probe=None, **kwargs):
        type(self).last_snapshot = snapshot
        ...


def test_agentteams_audit_passes_built_archive_path(tmp_path):
    _run_agentteams_audit(tmp_path)
    assert _FakeDriver.last_snapshot.archive_path.endswith(".zip")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_project_driver.py tests/unit/test_agentteams_cli_state.py -q
```

Expected: FAIL because `SnapshotReference` has no `archive_path`, and `_snapshot()` callers use the old signature.

- [ ] **Step 3: Add the minimal archive-path field and populate it**

Change `SnapshotReference` to:

```python
@dataclass(frozen=True)
class SnapshotReference:
    snapshot_id: str
    source_root: str
    files: tuple[dict, ...]
    archive_path: str
    archive_sha256: str
```

Populate it in `cli/argus.py`:

```python
snapshot_ref = SnapshotReference(
    snapshot_id=bundle.snapshot.snapshot_id,
    source_root="/root/hiclaw-fs/shared",
    files=tuple(...),
    archive_path=str(archive.resolve()),
    archive_sha256=bundle.archive_sha256,
)
```

Update every direct test constructor to supply a real path. There are only two production/test construction sites identified by the repository search: `cli/argus.py` and `tests/unit/test_project_driver.py`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/test_project_driver.py tests/unit/test_agentteams_cli_state.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the boundary change**

```bash
git add agentteams/worker_payloads.py cli/argus.py tests/unit/test_project_driver.py tests/unit/test_agentteams_cli_state.py
git commit -m "WIP: carry typed-task snapshot archive path

[gstack-context]
Decisions: SnapshotReference names the exact immutable ZIP created by WorkspaceSnapshotBuilder.
Remaining: publish the archive and create the AgentTeams Project Room.
Skill: /investigate
[/gstack-context]"
```

---

### Task 2: Publish shared binary files without text corruption

**Files:**
- Modify: `agentteams/hiclaw_client.py:392-415`
- Create: `tests/unit/test_hiclaw_client_shared_file.py`

**Interfaces:**
- Produces: `HiclawClient.publish_shared_file(relative_path: str, source_path: Path) -> None`.
- Consumes: existing `_shared_relative()`, `_docker_exec()`, `SHARED_ROOT`, and `STORAGE_ROOT`.
- Contract: MinIO upload succeeds before the Manager local mirror is replaced; source bytes survive unchanged.

- [ ] **Step 1: Write failing tests for byte preservation and remote-first publication**

Create `tests/unit/test_hiclaw_client_shared_file.py`:

```python
import base64
from pathlib import Path

import pytest

from agentteams.hiclaw_client import HiclawClient, HiclawError


def test_publish_shared_file_transports_exact_binary_bytes(tmp_path):
    source = tmp_path / "snapshot.zip"
    payload = b"PK\x03\x04\x00\xff\r\narchive"
    source.write_bytes(payload)
    calls = []
    client = HiclawClient(container="manager")

    def docker_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return ""

    client._docker_exec = docker_exec
    client.publish_shared_file("projects/proj-1/snapshot.zip", source)

    args, kwargs = calls[0]
    assert args[:3] == ("sh", "-c", args[2])
    assert base64.b64decode(kwargs["input_text"]) == payload
    assert str(HiclawClient.STORAGE_ROOT) + "/projects/proj-1/snapshot.zip" in args


def test_publish_shared_file_rejects_missing_source(tmp_path):
    client = HiclawClient(container="manager")
    with pytest.raises(HiclawError, match="shared source file does not exist"):
        client.publish_shared_file("projects/proj-1/snapshot.zip", tmp_path / "missing.zip")


def test_publish_shared_file_rejects_traversal(tmp_path):
    source = tmp_path / "snapshot.zip"
    source.write_bytes(b"x")
    client = HiclawClient(container="manager")
    with pytest.raises(HiclawError):
        client.publish_shared_file("../snapshot.zip", source)
```

The exact argument assertion should check that the generated shell script performs `base64 -d` into a private temporary file, then `mc cp "$tmp" "$2"`, then `cp "$tmp" "$1"` in that order.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_hiclaw_client_shared_file.py -q
```

Expected: FAIL with `AttributeError: 'HiclawClient' object has no attribute 'publish_shared_file'`.

- [ ] **Step 3: Implement binary-safe remote-first publication**

Add to `HiclawClient` next to `publish_shared_text()`:

```python
def publish_shared_file(self, relative_path: str, source_path: Path) -> None:
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
```

Do not modify `_docker_exec_in` text-mode behavior. The explicit base64 boundary keeps binary data out of UTF-8 decoding while preserving all existing callers.

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/test_hiclaw_client_shared_file.py -q
```

Expected: PASS.

- [ ] **Step 5: Run existing HiclawClient-focused tests**

Run:

```powershell
python -m pytest tests/unit/test_agentteams_skill_lock.py tests/unit/test_hiclaw_client_shared_file.py -q
```

Expected: PASS with no change to text publication or Skill packaging.

- [ ] **Step 6: Commit the binary publication primitive**

```bash
git add agentteams/hiclaw_client.py tests/unit/test_hiclaw_client_shared_file.py
git commit -m "WIP: publish typed-task snapshots as binary files

[gstack-context]
Decisions: Base64 crosses docker exec's text stdin; Manager decodes into a private temp file and publishes MinIO before the local mirror.
Remaining: create Project Room and wire room_id into tasks.
Skill: /investigate
[/gstack-context]"
```

---

### Task 3: Create the AgentTeams Project Room and publish the snapshot before tasks

**Files:**
- Modify: `agentteams/project_driver.py:83-170`
- Modify: `tests/unit/test_project_driver.py:11-203`

**Interfaces:**
- Consumes: `HiclawClient.create_project(project_id, title, workers) -> dict`, `publish_shared_file()`, `publish_shared_text()`, and `SnapshotReference.archive_path`.
- Produces: `_register_task(..., room_id: str, ...) -> dict`; every registered envelope carries the same real Project Room ID.
- Invariant: project creation and snapshot publication complete before the first `register_task()` call.

- [ ] **Step 1: Extend the fake client to record architecture-level events**

Update `FakeClient` in `tests/unit/test_project_driver.py`:

```python
class FakeClient:
    def __init__(self):
        ...
        self.events = []
        self.project_room_id = "!argus-project:matrix.test"
        self.binary_files = {}

    def create_project(self, project_id, title, workers):
        self.events.append(("create_project", project_id, tuple(workers)))
        return {"project_id": project_id, "project_room_id": self.project_room_id,
                "created_at": "2026-08-05T00:00:00Z"}

    def publish_shared_file(self, relative_path, source_path):
        self.events.append(("publish_shared_file", relative_path))
        self.binary_files[relative_path] = Path(source_path).read_bytes()

    def publish_shared_text(self, relative_path, content):
        self.events.append(("publish_shared_text", relative_path))

    def register_task(self, request):
        self.events.append(("register_task", request["task_id"]))
        ...
```

- [ ] **Step 2: Write failing Project Room and ordering tests**

Add:

```python
def test_run_creates_project_and_propagates_room_to_every_task(self):
    client = FakeAssessorClient()
    snapshot = _snapshot(self.tmp)
    outcome = _driver(client, self.tmp).run(
        {"project_id": "proj-room", "run_id": "run-room", "title": "Room audit"},
        snapshot,
    )
    self.assertEqual(outcome.status, "completed")
    self.assertEqual(client.events[0][0], "create_project")
    self.assertTrue(client.requests)
    self.assertEqual({request["room_id"] for request in client.requests},
                     {client.project_room_id})
    self.assertEqual(client.events.index(("publish_shared_file",
                                          "projects/proj-room/snapshot.zip")) <
                     next(i for i, event in enumerate(client.events)
                          if event[0] == "register_task"), True)


def test_run_stops_before_publish_or_register_when_project_has_no_room(self):
    client = FakeAssessorClient()
    client.project_room_id = ""
    with self.assertRaisesRegex(HiclawError, "AgentTeams project has no Project Room"):
        _driver(client, self.tmp).run({"project_id": "proj-no-room"},
                                      _snapshot(self.tmp))
    self.assertFalse(client.requests)
    self.assertNotIn("publish_shared_file", [event[0] for event in client.events])


def test_run_rejects_snapshot_digest_mismatch_before_registration(self):
    client = FakeAssessorClient()
    snapshot = replace(_snapshot(self.tmp), archive_sha256="0" * 64)
    with self.assertRaisesRegex(HiclawError, "snapshot archive digest mismatch"):
        _driver(client, self.tmp).run({"project_id": "proj-bad-snapshot"}, snapshot)
    self.assertFalse(client.requests)
```

Import `hashlib` and `replace` from `dataclasses` in the test file.

- [ ] **Step 3: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_project_driver.py -q
```

Expected: FAIL because `ProjectDriver` neither creates a Project nor publishes the archive, and `_register_task` still writes `room_id=""`.

- [ ] **Step 4: Implement Project creation, digest verification, and snapshot publication**

In `ProjectDriver`, add constants/helpers:

```python
PROJECT_WORKERS = tuple(
    f"argus-{role}" for role in (*ASSESSOR_ROLES, "meta", "synth")
)


def _publish_snapshot(self, project_id: str, snapshot: SnapshotReference) -> None:
    archive = Path(snapshot.archive_path).resolve()
    if not archive.is_file():
        raise HiclawError(f"snapshot archive missing: {archive}")
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected = snapshot.archive_sha256.removeprefix("sha256:")
    if actual != expected:
        raise HiclawError(
            f"snapshot archive digest mismatch: expected={expected} actual={actual}")
    self.client.publish_shared_file(
        f"projects/{project_id}/snapshot.zip", archive)
    self.client.publish_shared_text(
        f"projects/{project_id}/snapshot.id",
        json.dumps({"snapshot_id": snapshot.snapshot_id,
                    "archive_sha256": snapshot.archive_sha256}),
    )
```

Change `_register_task` to require `room_id`:

```python
def _register_task(self, project_id: str, room_id: str, task_id: str, ...):
    ...
    envelope = {
        ...,
        "room_id": room_id,
        ...,
    }
```

At the start of `run()` after IDs are derived:

```python
title = request.get("title") or f"Argus audit {run_id}"
project = self.client.create_project(project_id, title, PROJECT_WORKERS)
room_id = project.get("project_room_id")
if not isinstance(room_id, str) or not room_id:
    raise HiclawError("AgentTeams project has no Project Room")
self._publish_snapshot(project_id, snapshot)
```

Pass `room_id` to every `_register_task()` call, including assessor, Meta, revision, Synth, and report. Add `room_id` to `_revision_loop()` parameters so revisions stay in the same Project Room.

Do not call `sync_shared_directory()` after remote-first publication; `create_project()` already created and synced the project directory, while both publication methods update MinIO directly.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/test_project_driver.py tests/unit/test_hiclaw_client_shared_file.py -q
```

Expected: PASS.

- [ ] **Step 6: Run all non-live AgentTeams unit tests**

Run:

```powershell
python -m pytest tests/unit/test_project_driver.py tests/unit/test_agentteams_cli_state.py tests/unit/test_agentteams_skill_lock.py tests/unit/test_agentteams_results.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the AgentTeams-native Argus flow**

```bash
git add agentteams/project_driver.py tests/unit/test_project_driver.py
git commit -m "WIP: route typed tasks through AgentTeams project rooms

[gstack-context]
Decisions: ProjectDriver creates one Project Room, publishes snapshot.zip first, and places that room_id in every typed task.
Remaining: harden the fork's real Worker execution test and verify live A2/A4.
Skill: /investigate
[/gstack-context]"
```

---

### Task 4: Harden the AgentTeams real Worker execution test

**Files:**
- Modify: `E:/heishou/AgentTeams-v1.2.0-beta.1/tests/test-task-worker-execution.sh:1-96`
- Reuse: `tests/fixtures/deterministic-skill/**`
- Reuse: `tests/lib/test-helpers.sh`, `tests/lib/matrix-client.sh`, `tests/lib/minio-client.sh`

**Interfaces:**
- Consumes: live embedded AgentTeams, `hiclaw create/delete/get/task`, `create-project.sh`, Matrix admin login, Worker container naming helpers, and the deterministic Skill fixture.
- Produces: a nonzero-on-failure integration gate proving `Project Room -> Controller structured mention -> OpenClaw -> typed-task-execution -> hiclaw task execute -> COMPLETED` and duplicate-signal exactly-once behavior.

- [ ] **Step 1: Replace overwritten traps with one cleanup function**

The script must use one trap that removes the temp directory, task/project storage, Worker CR, and Worker container:

```bash
REG_DIR="$(mktemp -d)"
_cleanup() {
    rm -rf "${REG_DIR}"
    exec_in_agent hiclaw delete worker "${TEST_WORKER}" >/dev/null 2>&1 || true
    sleep 5
    remove_worker_container "${TEST_WORKER}"
    exec_in_manager mc rm -r --force "${STORAGE_PREFIX}/agents/${TEST_WORKER}/" >/dev/null 2>&1 || true
    exec_in_manager mc rm -r --force "${STORAGE_PREFIX}/tasks/${TEST_TASK}/" >/dev/null 2>&1 || true
    exec_in_manager mc rm -r --force "${STORAGE_PREFIX}/shared/projects/${TEST_PROJECT}/" >/dev/null 2>&1 || true
}
trap _cleanup EXIT
```

Source `tests/lib/matrix-client.sh` in addition to existing helpers.

- [ ] **Step 2: Make prerequisites explicit and failures truthful**

Require:

```bash
require_llm_key || {
    log_info "SKIP: typed-task Worker execution requires a configured LLM"
    test_teardown "task-worker-execution"
    test_summary
    exit 0
}

TEST_MODEL="${AGENTTEAMS_E2E_MODEL:-${AGENTTEAMS_DEFAULT_MODEL:-${HICLAW_E2E_MODEL:-${HICLAW_DEFAULT_MODEL:-qwen3.7-max}}}}"
```

Only missing external prerequisites may exit 0. Once Worker creation begins, registration, dispatch, state, artifact, and counter failures must call `log_fail` and end via `test_summary`, whose return code becomes the script exit code:

```bash
test_teardown "task-worker-execution"
test_summary
exit $?
```

Delete the existing register/dispatch `exit 0` blocks.

- [ ] **Step 3: Create and wait for a real OpenClaw Worker**

Use the existing CLI and helpers:

```bash
exec_in_agent hiclaw create worker \
    --name "${TEST_WORKER}" --model "${TEST_MODEL}" \
    --runtime openclaw --no-wait -o json >/dev/null || {
    log_fail "Worker creation failed"
    test_teardown "task-worker-execution"; test_summary; exit 1
}
wait_worker_provisioned "${TEST_WORKER}" 180 || {
    log_fail "Worker did not provision"
    test_teardown "task-worker-execution"; test_summary; exit 1
}
wait_for_worker_container "${TEST_WORKER}" 180 || {
    log_fail "Worker container did not start"
    test_teardown "task-worker-execution"; test_summary; exit 1
}
```

- [ ] **Step 4: Install the deterministic Skill and observed identity into the test Worker**

Resolve the actual container with `worker_container_name`, copy the fixture, and write observed state:

```bash
WORKER_CONTAINER="$(worker_container_name "${TEST_WORKER}")"
docker exec "${WORKER_CONTAINER}" mkdir -p "/root/hiclaw-fs/agents/${TEST_WORKER}/skills/deterministic-skill"
docker cp "${SCRIPT_DIR}/fixtures/deterministic-skill/." \
    "${WORKER_CONTAINER}:/root/hiclaw-fs/agents/${TEST_WORKER}/skills/deterministic-skill/"
GENERATION="generation-one"
SKILL_DIGEST="sha256:$(printf 'a%.0s' $(seq 1 64))"
docker exec -i "${WORKER_CONTAINER}" sh -c \
    "mkdir -p '/root/hiclaw-fs/agents/${TEST_WORKER}/.skills'; cat > '/root/hiclaw-fs/agents/${TEST_WORKER}/.skills/observed.json'" <<EOF
{"generation":"${GENERATION}","skills":[{"name":"deterministic-skill","version":"0.1.0","expected_digest":"${SKILL_DIGEST}","observed_digest":"${SKILL_DIGEST}","ready":true}]}
EOF
```

Remove any stale `.execution-counter` before dispatch.

- [ ] **Step 5: Create a real Project Room containing the Worker**

Invoke the exact built-in used by `HiclawClient.create_project()`:

```bash
PROJECT_OUT=$(exec_in_agent bash \
    /opt/hiclaw/agent/skills/project-management/scripts/create-project.sh \
    --id "${TEST_PROJECT}" --title "Typed task execution ${TEST_PROJECT}" \
    --workers "${TEST_WORKER}") || {
    log_fail "Project Room creation failed"
    test_teardown "task-worker-execution"; test_summary; exit 1
}
ROOM_ID=$(printf '%s\n' "${PROJECT_OUT}" | sed -n '/---RESULT---/,$p' | tail -n +2 | jq -r '.project_room_id // empty')
assert_not_empty "${ROOM_ID}" "Project Room created"
```

Project creation auto-invites and auto-joins the Worker. The Worker's existing wildcard group rule still requires the structured full-ID mention generated by Controller dispatch.

- [ ] **Step 6: Build a protocol-valid registration request**

Use a Python snippet to compute the exact Controller-compatible idempotency key from the same null-separated fields:

```bash
DEADLINE_ISO="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+1H +%Y-%m-%dT%H:%M:%SZ)"
IDEMPOTENCY_KEY=$(python3 - "${TEST_PROJECT}" "${TEST_TASK}" "${GENERATION}" "${SKILL_DIGEST}" <<'PY'
import hashlib, sys
project, task, generation, digest = sys.argv[1:]
fields = [project, task, "1", "deterministic-skill", "0.1.0", generation, digest, "v1"]
h = hashlib.sha256()
for field in fields:
    h.update(field.encode())
    h.update(b"\0")
print("sha256:" + h.hexdigest())
PY
)
```

Write `request.json` with the real `${ROOM_ID}`, assigned Worker, generation, digest, empty inputs, and the computed key. Register must fail the test on any nonzero exit.

- [ ] **Step 7: Dispatch and wait for real terminal completion**

After registration, read revision from the registration response, dispatch, then poll:

```bash
STATE=""
REVISION="$(printf '%s' "${REG_OUT}" | jq -r '.revision')"
exec_in_agent hiclaw task dispatch --id "${TEST_TASK}" --revision "${REVISION}" -o json >/dev/null || log_fail "Task dispatch failed"

DEADLINE=$(( $(date +%s) + 300 ))
while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
    TASK_JSON=$(exec_in_agent hiclaw task get --id "${TEST_TASK}" -o json 2>/dev/null || true)
    STATE=$(printf '%s' "${TASK_JSON}" | jq -r '.task.state // empty' 2>/dev/null)
    case "${STATE}" in
        COMPLETED|FAILED|BLOCKED|TIMED_OUT|CONFLICT) break ;;
    esac
    sleep 5
done
assert_eq "COMPLETED" "${STATE}" "Matrix signal executed typed task to completion"
```

Record whether ACKNOWLEDGED/RUNNING appeared when polling, but do not require observing every transient state; a fast deterministic Skill may move through them between polls. The terminal event history and final revision prove the transitions.

- [ ] **Step 8: Verify result and exactly-once duplicate signal behavior**

Read the result artifact:

```bash
RESULT=$(exec_in_manager mc cat "${STORAGE_PREFIX}/tasks/${TEST_TASK}/artifacts/result.json" 2>/dev/null || true)
assert_eq "completed" "$(printf '%s' "${RESULT}" | jq -r '.status // empty')" "Result status completed"
assert_eq "1" "$(printf '%s' "${RESULT}" | jq -r '.execution_count // empty')" "First signal executed Skill once"
```

Log in as admin, send the same visible full-ID Matrix executable signal to the Project Room, wait 30 seconds, and inspect the local counter:

```bash
ADMIN_LOGIN=$(matrix_login "${TEST_ADMIN_USER}" "${TEST_ADMIN_PASSWORD}")
ADMIN_TOKEN=$(printf '%s' "${ADMIN_LOGIN}" | jq -r '.access_token // empty')
WORKER_MXID="@${TEST_WORKER}:${TEST_MATRIX_DOMAIN}"
matrix_send_mention_message "${ADMIN_TOKEN}" "${ROOM_ID}" "${WORKER_MXID}" \
    "ARGUS_TYPED_TASK task_id=${TEST_TASK} envelope=tasks/${TEST_TASK}/dispatch/envelope.json" >/dev/null
sleep 30
COUNTER=$(docker exec "${WORKER_CONTAINER}" cat \
    "/root/hiclaw-fs/agents/${TEST_WORKER}/skills/deterministic-skill/implementation/.execution-counter" 2>/dev/null || true)
assert_eq "1" "${COUNTER}" "Duplicate executable signal did not rerun Skill"
```

Note: `matrix_send_mention_message` prepends the visible Worker ID, while Worker routing requires the current message to begin with `ARGUS_TYPED_TASK`. For this duplicate step, add a small test-local helper payload that keeps `ARGUS_TYPED_TASK` first in `body`, appends the full Worker ID, and includes `m.mentions.user_ids`; do not change the shared helper's public behavior. This mirrors `TaskHandler.Dispatch` exactly.

- [ ] **Step 9: Run the shell test against the live environment**

Run from the AgentTeams fork:

```bash
bash tests/test-task-worker-execution.sh
```

Expected: nonzero on any runtime failure; PASS proves Project Room creation, structured Matrix signal delivery, OpenClaw routing, typed executor completion, result publication, and duplicate-signal counter `1`.

If this test returns HTTP 401 from a fresh Worker, stop implementation and capture:

```bash
docker inspect "$(worker_container_name "${TEST_WORKER}")" --format '{{.Created}} {{range .Config.Env}}{{println .}}{{end}}'
docker logs agentteams-controller 2>&1 | tail -200
docker exec "$(worker_container_name "${TEST_WORKER}")" hiclaw task get --id "${TEST_TASK}" -o json
```

Do not add token rotation in this task. Report the evidence and open a separate design decision.

- [ ] **Step 10: Commit only the fork test**

From `E:/heishou/AgentTeams-v1.2.0-beta.1`:

```bash
git add tests/test-task-worker-execution.sh
git diff --cached --name-only
git commit -m "test: prove typed tasks execute through project rooms"
```

Expected staged file list: only `tests/test-task-worker-execution.sh`. Confirm `install/hiclaw-install.ps1` remains modified and unstaged.

---

### Task 5: Verify Argus A2/A4 through real AgentTeams Workers

**Files:**
- No implementation files unless verification exposes a reproduced defect.
- Generated evidence only: `.argus/acceptance/**` and `acceptance.md` remain uncommitted.

**Interfaces:**
- Consumes: Tasks 1-4, the existing six Argus Workers, AgentTeams live environment, and Koubo read-only target.
- Produces: fresh command output proving terminal task states and truthful acceptance outcomes.

- [ ] **Step 1: Run the full local Argus suite**

Run:

```powershell
python -m pytest -m "not agentteams" -q
```

Expected: all tests pass. If failures are unrelated pre-existing failures, record exact names/output and do not claim completion.

- [ ] **Step 2: Run the existing live AgentTeams pytest suite**

Run:

```powershell
$env:ARGUS_AGENTTEAMS_E2E = "1"
python -m pytest -m agentteams -q
Remove-Item Env:\ARGUS_AGENTTEAMS_E2E
```

Expected: all live tests pass.

- [ ] **Step 3: Run direct A2 vulnerable-demo audit**

Run:

```powershell
python -m cli.argus audit `
  --target "demo\scenarios\ai-pr-three-defects\vulnerable" `
  --headless `
  --engine agentteams `
  --registry-fixture "demo\scenarios\ai-pr-three-defects\registry-fixture.json"
```

Expected:

- process exit `2`;
- stdout includes `status=completed`;
- assessor tasks do not remain `DISPATCHED`;
- release gate blocks the vulnerable demo.

- [ ] **Step 4: Run direct A4 Koubo audit read-only**

Before and after the audit, capture Koubo status and content hash using the project's established acceptance command or `git -C E:/heishou/koubo status --porcelain` plus the existing leakage integrity helper. Run:

```powershell
python -m cli.argus audit `
  --target "E:\heishou\koubo" `
  --headless `
  --engine agentteams
```

Expected:

- exit is one of the defined truthful gate exits `0`, `1`, `2`, or `3`;
- stdout includes `status=completed`;
- Koubo status/hash is unchanged;
- no task remains `DISPATCHED` after timeout.

- [ ] **Step 5: Run full phase-one acceptance**

Run:

```powershell
python -m cli.argus acceptance phase-one `
  --target "E:\heishou\koubo" `
  --workspace-mode current-source `
  --agentteams-live `
  --leakage-e2e
```

Expected for this implementation:

- A2 passes through real Workers and blocks the vulnerable demo;
- A4 reaches a truthful terminal outcome through real Workers;
- any independent A8 document-length failure remains honestly reported until separately fixed;
- generated evidence identifies the Project/task states and does not claim `COMPLETED` on crash or timeout.

- [ ] **Step 6: Inspect repository state and protect unrelated work**

Run:

```powershell
git status --short
git -C "E:\heishou\AgentTeams-v1.2.0-beta.1" status --short
```

Confirm:

- Argus generated `.argus/`, `acceptance.md`, and caches are not staged;
- AgentTeams `install/hiclaw-install.ps1` is still unstaged and unchanged by this task;
- no Worker/controller image rebuild was performed because runtime implementation was reused unchanged.

- [ ] **Step 7: Record the verified logical unit**

If all required tests pass, stage only intentional Argus source/tests/docs not already committed. Do not stage generated acceptance files:

```bash
git add agentteams/worker_payloads.py agentteams/hiclaw_client.py agentteams/project_driver.py cli/argus.py tests/unit/test_project_driver.py tests/unit/test_agentteams_cli_state.py tests/unit/test_hiclaw_client_shared_file.py docs/superpowers/specs/2026-08-05-agentteams-native-typed-task-design.md docs/superpowers/plans/2026-08-05-agentteams-native-typed-task-implementation.md
git diff --cached --name-only
git commit -m "WIP: complete AgentTeams-native typed task execution

[gstack-context]
Decisions: Argus uses Project Room Matrix signals and the existing typed-task executor; snapshot.zip is published before registration; no queue poller.
Remaining: address only independently failing acceptance items such as A8.
Skill: /investigate
[/gstack-context]"
```

If a required test fails, do not create this completion commit. Keep verification task open and report the exact failure.

---

## Self-Review Results

- **Spec coverage:** Project creation, room propagation, binary snapshot publication, remote-first storage, structured Matrix wake-up reuse, OpenClaw typed execution, duplicate-signal exactly-once testing, truthful failure behavior, A2/A4 verification, and token-rotation deferral each map to an explicit task.
- **Placeholders:** No `TBD`, `TODO`, “implement later,” generic error-handling instruction, or undefined production interface remains.
- **Type consistency:** `SnapshotReference.archive_path` is introduced before use; `publish_shared_file(relative_path: str, source_path: Path)` is defined before `ProjectDriver` consumes it; `_register_task` and `_revision_loop` consistently carry `room_id: str`.
- **Scope:** Runtime code changes are limited to Argus. AgentTeams fork changes only its false-positive live test because the required Project Room, structured mention, Worker routing, and executor already exist.
