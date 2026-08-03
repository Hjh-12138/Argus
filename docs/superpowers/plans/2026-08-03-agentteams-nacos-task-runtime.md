# AgentTeams Nacos Skill Runtime and Typed Task Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the pinned AgentTeams fork so existing Nacos `remoteSkills` converge atomically into local Worker runtimes and generic typed Tasks execute once with durable ACK/result state.

**Architecture:** Preserve AgentTeams' existing `remoteSkills` control plane and remove the interrupted package-manifest-v2 experiment. The Controller downloads exact Nacos Skill versions, stages one complete multi-Skill generation in MinIO, and publishes a desired pointer only after verification; the Worker atomically activates that generation and reports observed versions/digests. A separate generic Task service stores immutable envelopes and typed artifacts in MinIO, while Matrix carries only bounded wake-up IDs.

**Tech Stack:** Go 1.25+, AgentTeams v1.2.0-beta.1 at upstream commit `78d0ceda336befa6e62bf89fc1a6b08b965e128d`, Nacos AI Registry API, MinIO through `internal/oss.StorageClient`, Matrix, Python 3 Worker helper, POSIX shell, Docker/OCI labels.

## Global Constraints

- Work in `E:\heishou\AgentTeams-v1.2.0-beta.1`; Go module root is `hiclaw-controller/`.
- The checkout is detached at upstream tag `v1.2.0-beta.1`; create the fork branch only when the retained work has been separated from unrelated changes.
- Never edit, restore, stage, or commit `install/hiclaw-install.ps1`; its existing AppService/BOM changes predate this task.
- Do not edit `E:\heishou\koubo`.
- Nacos `source + name + version` is the release identity. Labels and unversioned references remain supported generically, but Argus formal audits use explicit versions only.
- Directory SHA-256 is automatically computed runtime evidence, not a new `RemoteSkill` configuration field.
- Preserve `WorkerSpec.Skills` as built-in Skills only. Custom Argus Skills use existing `RemoteSkills`.
- Preserve legacy Worker package seed-only behavior. Do not add package manifest v2 or `managed_artifacts` semantics.
- Skill generation activation may modify only remote-Skill directories owned by the previous observed generation.
- Matrix is wake-up transport only. MinIO Task state and typed artifacts are authoritative.
- Task state never moves backward. Every mutation requires an expected revision.
- A Worker must validate assignment, deadline, input digests, active Skill version/generation, and idempotency key before ACK.
- Write each task's tests before production changes, but do not execute any test command until Task 7. This is the user's explicit exception for the interrupted implementation session.
- Do not mark Tasks 1–6 verified or create clean feature commits until Task 7 executes the queued suites. Continuous checkpoint mode may create `WIP:` commits only for internally coherent, compile-intended units; never stage unrelated files.

---

## Current Interrupted Workspace Classification

### Retain and complete

- `hiclaw-controller/internal/task/types.go`
- `hiclaw-controller/internal/task/store.go`
- `hiclaw-controller/internal/task/store_test.go`
- `hiclaw-controller/internal/server/task_handler.go`
- `hiclaw-controller/internal/server/task_handler_test.go`
- `hiclaw-controller/cmd/hiclaw/task_cmd.go`
- `hiclaw-controller/cmd/hiclaw/task_cmd_test.go`
- `hiclaw-controller/internal/buildinfo/buildinfo.go`
- `hiclaw-controller/internal/buildinfo/buildinfo_test.go`
- `hiclaw-controller/internal/server/status_handler_test.go`
- Task route wiring in `internal/server/http.go`
- Matrix structured mention support in `internal/matrix/client.go`
- Task authorization in `internal/auth/authorizer.go`
- `manager/agent/worker-agent/skills/typed-task-execution/`
- typed-task precedence in `manager/agent/worker-agent/AGENTS.md`
- Worker local-to-remote exclusions for `skills/**` and Task state

### Migrate into the Nacos `remoteSkills` path

- safe archive validation ideas from `internal/executor/package_manifest.go`
- canonical directory hashing from `internal/executor/package_manifest.go`
- generation descriptor/staging ideas from `internal/executor/managed_artifacts.go`
- atomic activation/rollback ideas from `worker/scripts/managed-artifacts-sync.py`

### Remove after migration

- `hiclaw-controller/internal/executor/package_manifest.go`
- `hiclaw-controller/internal/executor/package_extracted.go`
- `hiclaw-controller/internal/executor/managed_artifacts.go`
- package-v2-only tests
- package-v2 changes in `internal/executor/package.go`
- package-v2 response changes in `internal/server/package_handler.go`
- the `managed-artifacts-sync.py` filename and `.managed` contract
- the second package-specific convergence loop in `worker-entrypoint.sh`

---

## File Structure

### New focused units

- `hiclaw-controller/internal/executor/skill_archive.go` — safe Nacos Skill archive extraction and canonical directory digest.
- `hiclaw-controller/internal/service/remote_skill_generation.go` — collect exact remote Skills, stage/re-read a complete MinIO generation, and publish desired state.
- `hiclaw-controller/internal/service/remote_skill_generation_test.go` — generation, stale-file, and ownership tests.
- `worker/scripts/remote-skills-sync.py` — Worker-side complete generation download, atomic activation, rollback, and observed state.
- `worker/scripts/test_remote_skills_sync.py` — filesystem-level activation tests.
- `tests/test-remote-skills-generation.sh` — container integration for Nacos-to-Worker convergence.
- `tests/fixtures/deterministic-skill/` — one self-contained JSON Skill for Task execution tests.
- `tests/test-task-worker-execution.sh` — real Matrix wake-up and exactly-once execution integration.

### Existing integration points

- `hiclaw-controller/internal/executor/nacos_ai_service.go` — exact-version archive download.
- `hiclaw-controller/internal/service/deployer.go` — replace direct per-Skill mirror with generation staging.
- `hiclaw-controller/internal/oss/{client.go,minio.go,ossfake/memory.go}` — deterministic recursive listing.
- `worker/scripts/worker-entrypoint.sh` — run one remote-Skill convergence loop without direct remote Skill overwrite.
- `hiclaw-controller/internal/task/` — generic Task state service.
- `hiclaw-controller/internal/server/{http.go,task_handler.go,status_handler.go}` — API and version identity.
- `hiclaw-controller/cmd/hiclaw/{main.go,task_cmd.go}` — Task CLI and one-shot executor.
- `Makefile`, `hiclaw-controller/Dockerfile`, `manager/Dockerfile`, `worker/Dockerfile` — linker identity and OCI labels.

---

### Task 1: Remove Package-v2 Skill Governance Without Losing Generic Helpers

**Files:**
- Create: `hiclaw-controller/internal/executor/skill_archive.go`
- Create: `hiclaw-controller/internal/executor/skill_archive_test.go`
- Modify: `hiclaw-controller/internal/executor/nacos_ai_service.go:69-176`
- Modify: `hiclaw-controller/internal/executor/package.go:167-185`
- Modify: `hiclaw-controller/internal/server/package_handler.go:23-84`
- Delete: `hiclaw-controller/internal/executor/package_manifest.go`
- Delete: `hiclaw-controller/internal/executor/package_manifest_test.go`
- Delete: `hiclaw-controller/internal/executor/package_extracted.go`
- Delete: `hiclaw-controller/internal/executor/managed_artifacts.go`
- Delete: `hiclaw-controller/internal/executor/managed_artifacts_test.go`

**Interfaces:**
- Produces: `ExtractSkillArchive(zipPath, outputDir string) error`
- Produces: `DigestSkillDirectory(root string) (string, error)` returning `sha256:<64 lowercase hex>`.
- Produces: `ValidateSkillDirectory(root, expectedName string) error`.
- Preserves: `NacosAIClient.GetSkill(ctx, name, outputDir, version, label) error`.
- Preserves: legacy `PackageResolver.DeployToMinIO(...)` seed-only behavior.
- Consumed by: Task 2 generation staging and Task 3 Worker parity tests.

- [ ] **Step 1: Write archive and digest contract tests first**

Create tests that construct ZIPs and assert:

```go
func TestExtractSkillArchiveRejectsTraversalAndSymlink(t *testing.T) {
    for _, entry := range []zipEntry{
        {name: "../escape", body: []byte("bad")},
        {name: "argus-demo/link", body: []byte("/etc/passwd"), mode: os.ModeSymlink | 0o777},
    } {
        zipPath := writeSkillZip(t, []zipEntry{entry})
        if err := ExtractSkillArchive(zipPath, t.TempDir()); err == nil {
            t.Fatalf("expected unsafe entry %q to fail", entry.name)
        }
    }
}

func TestDigestSkillDirectoryCoversSortedPathsAndBytes(t *testing.T) {
    root := t.TempDir()
    writeFile(t, root, "SKILL.md", "# Demo\n")
    writeFile(t, root, "implementation/main.py", "print('ok')\n")
    first, err := DigestSkillDirectory(root)
    if err != nil { t.Fatal(err) }
    writeFile(t, root, "implementation/main.py", "print('changed')\n")
    second, err := DigestSkillDirectory(root)
    if err != nil { t.Fatal(err) }
    if first == second { t.Fatal("digest ignored changed bytes") }
}
```

Add structure cases requiring `<expectedName>/SKILL.md`, a manifest file, schemas, and `implementation/main.py` for executable Skills while allowing generic documentation-only remote Skills when no execution stanza exists.

- [ ] **Step 2: Queue the deferred RED command**

Do not run now. Add to Task 7's command ledger:

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./internal/executor -run 'SkillArchive|DigestSkillDirectory' -v
```

Expected when eventually run against pre-implementation state: missing `ExtractSkillArchive`/`DigestSkillDirectory` symbols.

- [ ] **Step 3: Implement the generic archive helpers**

Use `archive/zip`, reject backslashes, absolute paths, `..`, symlinks, and special files. Digest regular files exactly as:

```go
names := sortedRelativePOSIXPaths(root)
h := sha256.New()
for _, name := range names {
    io.WriteString(h, name)
    h.Write([]byte{0})
    h.Write(readFile(name))
    h.Write([]byte{0})
}
return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
```

`GetSkill` must download to a private temp file, call `ExtractSkillArchive`, validate the requested Skill root, and return no archive contents in error messages.

- [ ] **Step 4: Restore legacy package semantics exactly**

Remove the `ParsePackage` call from package upload and remove the v2 branch from `DeployToMinIO`. `POST /api/v1/packages` returns only its pre-fork-compatible `packageUri`. Keep the 64 MiB upload bound if it is independently useful, but do not expose `manifestVersion` or `managedArtifacts`.

- [ ] **Step 5: Delete superseded package-v2 files and confirm the migration boundary**

Review the intentional diff list. It must contain no package-v2 symbol:

```text
ParsePackage
ManagedArtifactManifest
ManagedArtifactInventory
StageManagedGeneration
parseExtractedManagedPackage
managed_artifacts
```

Do not use a repository-wide reset. Do not touch `install/hiclaw-install.ps1`.

- [ ] **Step 6: Defer commit until Task 7**

Stage nothing yet. Record the intended verified commit message:

```text
refactor: keep custom skills on the Nacos control plane
```

---

### Task 2: Stage Complete Nacos Remote-Skill Generations

**Files:**
- Create: `hiclaw-controller/internal/service/remote_skill_generation.go`
- Create: `hiclaw-controller/internal/service/remote_skill_generation_test.go`
- Modify: `hiclaw-controller/internal/service/deployer.go:738-763,916-1047`
- Modify: `hiclaw-controller/internal/oss/client.go:28-32`
- Modify: `hiclaw-controller/internal/oss/minio.go:169-191`
- Modify: `hiclaw-controller/internal/oss/minio_test.go`
- Modify: `hiclaw-controller/internal/oss/ossfake/memory.go:110-122`
- Retain/adjust: `hiclaw-controller/internal/oss/list_objects_test.go`

**Interfaces:**
- Produces:

```go
type RemoteSkillCoordinate struct {
    Source  string `json:"source"`
    Name    string `json:"name"`
    Version string `json:"version,omitempty"`
    Label   string `json:"label,omitempty"`
    Digest  string `json:"digest"`
}

type RemoteSkillGeneration struct {
    SchemaVersion string                  `json:"schema_version"`
    Generation    string                  `json:"generation"`
    Skills        []RemoteSkillCoordinate `json:"skills"`
    CreatedAt     string                  `json:"created_at"`
}
```

- Produces: `StageRemoteSkillGeneration(ctx context.Context, storage oss.StorageClient, worker string, fetched []FetchedRemoteSkill) (*RemoteSkillGeneration, error)`.
- Produces: recursive deterministic `ListObjects(ctx, prefix) ([]string, error)` with complete keys relative to the configured storage prefix.
- Modifies: `pushRemoteSkills` to fetch all declarations first and publish one generation.
- Consumed by: Task 3 Worker activation and Argus live readiness checks.

- [ ] **Step 1: Write generation tests first**

Cover complete stage, deterministic identity, read-back digest verification, multiple Skills, failure before desired switch, and removal ownership:

```go
func TestStageRemoteSkillGenerationDoesNotSwitchDesiredOnPartialFailure(t *testing.T) {
    memory := ossfake.NewMemory()
    seedDesired(t, memory, "alice", "old-generation")
    storage := failOnPut{StorageClient: memory, suffix: "implementation/main.py"}
    _, err := StageRemoteSkillGeneration(ctx, storage, "alice", fetchedSkills(t))
    if err == nil { t.Fatal("expected staging failure") }
    assertDesiredGeneration(t, memory, "alice", "old-generation")
}

func TestGenerationIdentityIncludesSourceNameVersionAndDigest(t *testing.T) {
    a := generationID([]RemoteSkillCoordinate{{Source:"nacos://private/argus", Name:"argus-sec", Version:"1.0.0", Digest:"sha256:"+strings.Repeat("a",64)}})
    b := generationID([]RemoteSkillCoordinate{{Source:"nacos://private/argus", Name:"argus-sec", Version:"1.0.1", Digest:"sha256:"+strings.Repeat("a",64)}})
    if a == b { t.Fatal("version did not affect generation") }
}
```

Add a generic compatibility test proving label-based non-Argus Skills still stage, while no caller mistakes a label for an immutable version.

- [ ] **Step 2: Queue deferred RED commands**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./internal/service -run 'RemoteSkillGeneration|PushRemoteSkills' -v
go test ./internal/oss/... -run 'ListObjects|MCFind' -v
```

- [ ] **Step 3: Make MinIO listing recursive and normalized**

Replace `mc ls` parsing with a recursive machine-readable command such as:

```text
mc find <full-prefix> --print {key}
```

Strip `config.StoragePrefix + "/"` exactly once, reject keys outside the prefix, sort results, and return complete object keys. Keep `ossfake.Memory` behavior identical.

- [ ] **Step 4: Fetch all remote Skills before publishing anything**

Refactor `pushRemoteSkills` so it:

1. validates each source and coordinate;
2. fetches each Skill to an isolated temp root;
3. calls `ValidateSkillDirectory` and `DigestSkillDirectory`;
4. builds `[]FetchedRemoteSkill`;
5. invokes `StageRemoteSkillGeneration` once;
6. never mirrors fetched remote Skills into `agents/<worker>/skills/<name>/` directly.

A failure on the fifth Skill must leave all previous active Skills unchanged.

- [ ] **Step 5: Stage and independently verify the generation**

Write files under:

```text
agents/<worker>/.skills/generations/<generation>/skills/<name>/...
```

After upload, re-list and re-read every object, recompute every directory digest, then write `descriptor.json`, followed by the single pointer:

```text
agents/<worker>/.skills/desired.json
```

`desired.json` contains only schema version and generation ID. Never delete the previous generation in this task.

- [ ] **Step 6: Defer commit until Task 7**

Intended verified commit:

```text
feat: stage complete Nacos skill generations
```

---

### Task 3: Atomically Activate Remote Skills in Workers

**Files:**
- Create: `worker/scripts/remote-skills-sync.py`
- Create: `worker/scripts/test_remote_skills_sync.py`
- Create: `tests/test-remote-skills-generation.sh`
- Modify: `worker/scripts/worker-entrypoint.sh:159-251`
- Delete: `worker/scripts/managed-artifacts-sync.py`
- Delete: `worker/scripts/test_managed_artifacts_sync.py`

**Interfaces:**
- Worker command: `python3 /opt/hiclaw/scripts/remote-skills-sync.py`.
- Reads: `agents/<worker>/.skills/desired.json` and generation descriptor/files.
- Writes local and MinIO: `agents/<worker>/.skills/observed.json`.
- Observed fields:

```json
{
  "schema_version": "1",
  "generation": "sha256-identity",
  "skills": [
    {
      "source": "nacos://host/namespace",
      "name": "argus-secret-scan",
      "version": "1.0.0",
      "expected_digest": "sha256:...",
      "observed_digest": "sha256:...",
      "ready": true
    }
  ]
}
```

- Consumed by: Task 5 pre-ACK validation and Argus A5.

- [ ] **Step 1: Write filesystem activation tests first**

Test successful multi-Skill activation, stale-file deletion, unmanaged Skill preservation, second-Skill failure rollback, invalid descriptor path, digest mismatch, lock contention, and idempotent same-generation sync.

```python
def test_second_skill_failure_rolls_back_complete_set(tmp_path):
    workspace = seed_active_generation(tmp_path, {
        "argus-a": {"SKILL.md": b"old-a"},
        "argus-b": {"SKILL.md": b"old-b"},
    })
    staged = seed_staged_generation(tmp_path, {
        "argus-a": {"SKILL.md": b"new-a"},
        "argus-b": {"SKILL.md": b"new-b"},
    })
    (staged / "skills" / "argus-b" / "SKILL.md").unlink()
    with pytest.raises(SyncError):
        activate_generation(workspace, staged, descriptor_for(staged))
    assert (workspace / "skills/argus-a/SKILL.md").read_bytes() == b"old-a"
    assert (workspace / "skills/argus-b/SKILL.md").read_bytes() == b"old-b"
```

Use `unittest` instead of pytest only if Worker images do not contain pytest; the production helper must remain standard-library-only.

- [ ] **Step 2: Queue deferred RED commands**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1
python -m unittest -v worker/scripts/test_remote_skills_sync.py
bash tests/test-remote-skills-generation.sh
```

- [ ] **Step 3: Implement safe descriptor parsing and digest parity**

Allow only names matching `^[a-z][a-z0-9-]{2,63}$`. Build active paths as `workspace / "skills" / name`; reject absolute paths and traversal. Implement the same path/NUL/bytes/NUL digest as Go.

- [ ] **Step 4: Implement complete-set activation and rollback**

Use one lock directory or OS lock under `.skills/activation.lock`. Move only Skill directories listed in the prior observed document or new descriptor into a rollback root, activate all staged directories, verify every active digest, then write observed state. On any exception, remove partial new directories and restore every prior directory.

Do not delete rollback immediately. Write a `pending_cleanup_generation` field or marker so Task 5 can mark the generation used; cleanup remains bounded and explicit.

- [ ] **Step 5: Integrate one convergence loop**

In `worker-entrypoint.sh`:

- keep local-to-remote exclusion of `skills/**`, `.skills/**`, and `.tasks/**`;
- keep the legacy fallback mirror for built-in/Manager-owned `agents/<worker>/skills/`;
- ensure Controller remote generations never live under that direct MinIO prefix;
- run only `remote-skills-sync.py` every five seconds;
- remove every `.managed`/`managed-artifacts-sync.py` reference.

- [ ] **Step 6: Add container integration fixture**

`tests/test-remote-skills-generation.sh` must publish a fake generation A, verify active bytes and observed state, publish generation B that changes/adds/removes files, verify stale removal and unmanaged preservation, then publish a broken generation and verify rollback to B.

- [ ] **Step 7: Defer commit until Task 7**

Intended verified commit:

```text
feat: activate remote skill generations atomically
```

---

### Task 4: Complete the Generic MinIO Task Service and HTTP/CLI Surface

**Files:**
- Modify: `hiclaw-controller/internal/task/types.go`
- Modify: `hiclaw-controller/internal/task/store.go`
- Modify: `hiclaw-controller/internal/task/store_test.go`
- Modify: `hiclaw-controller/internal/server/task_handler.go`
- Modify: `hiclaw-controller/internal/server/task_handler_test.go`
- Modify: `hiclaw-controller/internal/server/http.go:101-107`
- Modify: `hiclaw-controller/internal/auth/authorizer.go`
- Modify: `hiclaw-controller/internal/auth/authorizer_test.go`
- Modify: `hiclaw-controller/internal/matrix/client.go:69-73,772-796`
- Modify: `hiclaw-controller/internal/matrix/client_test.go`
- Modify: `hiclaw-controller/cmd/hiclaw/main.go`
- Modify: `hiclaw-controller/cmd/hiclaw/task_cmd.go`
- Modify: `hiclaw-controller/cmd/hiclaw/task_cmd_test.go`

**Interfaces:**
- HTTP:

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{id}
POST /api/v1/tasks/{id}/dispatch
POST /api/v1/tasks/{id}/ack
POST /api/v1/tasks/{id}/start
POST /api/v1/tasks/{id}/result
POST /api/v1/tasks/{id}/terminal
```

- CLI:

```text
hiclaw task register --file <json> -o json
hiclaw task get --id <id> -o json
hiclaw task dispatch --id <id> --revision <n> -o json
hiclaw task ack --id <id> --revision <n> -o json
hiclaw task start --id <id> --revision <n> -o json
hiclaw task result --id <id> --revision <n> --artifact <json> --summary <text> -o json
hiclaw task terminal --id <id> --revision <n> --state <state> --code <public-code> -o json
```

- Task envelope adds `skill_version` and `skill_generation` beside `skill`.
- Store persists immutable `base/request.json`, `dispatch/envelope.json`, `meta.json`, numbered immutable events, typed result, and summary.
- Consumed by: Task 5 executor and Argus protocol client.

- [ ] **Step 1: Complete tests before touching implementation**

Add cases for:

- divergent registration with the same Task ID;
- one-way transitions;
- stale revisions;
- exactly one `DISPATCHED → DISPATCHED` retry event;
- second retry rejection;
- deadline and attempt validation;
- result required before `COMPLETED`;
- identical duplicate result;
- divergent result conflict;
- Manager register/dispatch and Worker self-only ack/start/result/terminal;
- bounded structured Matrix mention with `m.mentions.user_ids`;
- no input payload in Matrix body.

The dispatch record must carry a retry count so unlimited same-state transitions are impossible.

- [ ] **Step 2: Queue deferred RED commands**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./internal/task ./internal/server ./internal/auth ./internal/matrix ./cmd/hiclaw -run 'Task|Mention' -v
go test -race ./internal/task -v
```

- [ ] **Step 3: Normalize Task types and validation**

Use regular formatted Go structs rather than semicolon-packed declarations. Require schema version `1`, safe IDs, UTC deadline, attempt ≥1, SHA-256 input digests, relative input paths, non-empty Skill name/version/generation, output schema path, and exact recomputed idempotency key.

Idempotency key inputs are:

```text
project_id, task_id, attempt, skill, skill_version, skill_generation,
agent_version, sorted(path, sha256) inputs
```

- [ ] **Step 4: Enforce immutable registration and single-Controller CAS**

Canonical-JSON hash the complete registration request and persist `request_digest` in the Task record. An identical request returns the existing Task; any changed request for the same ID returns revision conflict. Keep a keyed per-Task mutex and document the phase-one single-Controller limitation.

- [ ] **Step 5: Split explicit transition handlers and CLI commands**

Replace the generic public `/transition` route with explicit ack/start/terminal routes. Each handler sets its allowed target state server-side. Preserve internal `Store.Transition` for state-machine reuse.

- [ ] **Step 6: Persist before Matrix and allow one bounded retry**

Dispatch writes state/event before calling Matrix. The body is exactly bounded to IDs:

```text
ARGUS_TYPED_TASK task_id=<id> envelope=tasks/<id>/dispatch/envelope.json @<worker-id>
```

A Matrix failure returns 502 while the Task remains `DISPATCHED`. One later dispatch with the current revision increments `dispatch_count`; a third dispatch is rejected with 409.

- [ ] **Step 7: Map errors deterministically**

Use:

```text
400 invalid schema/request
403 Worker ownership violation
404 Task missing
409 revision/transition/result conflict
500 storage failure
502 durable dispatch but Matrix wake-up failure
```

Never return raw Task payload or storage command stderr.

- [ ] **Step 8: Defer commit until Task 7**

Intended verified commit:

```text
feat: expose reliable typed task state
```

---

### Task 5: Execute Versioned Nacos Skills from Matrix-Awakened Workers

**Files:**
- Modify: `hiclaw-controller/cmd/hiclaw/task_cmd.go`
- Modify: `hiclaw-controller/cmd/hiclaw/task_cmd_test.go`
- Modify: `manager/agent/worker-agent/AGENTS.md:114-126`
- Modify: `manager/agent/worker-agent/skills/typed-task-execution/SKILL.md`
- Modify: `manager/agent/worker-agent/skills/typed-task-execution/manifest.yaml`
- Create: `tests/fixtures/deterministic-skill/SKILL.md`
- Create: `tests/fixtures/deterministic-skill/manifest.yaml`
- Create: `tests/fixtures/deterministic-skill/schemas/input.schema.json`
- Create: `tests/fixtures/deterministic-skill/schemas/output.schema.json`
- Create: `tests/fixtures/deterministic-skill/implementation/main.py`
- Create: `tests/test-task-worker-execution.sh`

**Interfaces:**
- CLI: `hiclaw task execute --id <id> -o json`.
- Reads Worker observed state at `<workspace>/.skills/observed.json`.
- Skill manifest execution:

```yaml
execution:
  command: ["python", "implementation/main.py"]
  input: json-file
  output: json-file
  timeoutSeconds: 300
```

- Uses JSON Schema from the active Skill package to validate output. Add a focused Go JSON Schema dependency if no existing validator can validate draft 2020-12; pin it in `go.mod`/`go.sum`.
- Produces one Task typed artifact and one bounded `result.md`.

- [ ] **Step 1: Write pre-ACK and exactly-once tests first**

Test:

- assignment mismatch;
- expired deadline;
- unsafe or missing input path;
- input digest mismatch;
- active Skill name/version/generation mismatch;
- idempotency mismatch;
- no ACK on any failed precondition;
- exactly one ACK and RUNNING transition;
- clean environment and bounded timeout;
- output JSON/schema validation;
- duplicate wake-up reuses persisted identical result without executing again;
- changed duplicate result forces conflict;
- bounded public failure codes with no raw stderr.

Use an `httptest.Server` as the real Task API boundary rather than mocking `executeTask` internals.

- [ ] **Step 2: Queue deferred RED commands**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./cmd/hiclaw -run 'TaskExecute|ValidateTaskEnvelope' -v
cd ..
bash tests/test-task-worker-execution.sh
```

- [ ] **Step 3: Validate every precondition before ACK**

Resolve only input paths beneath configured allowlisted roots. Use `filepath.Rel` and reject `..`. Recompute every SHA-256 and idempotency key. Parse observed state and require matching ready `name`, `version`, and `generation`.

- [ ] **Step 4: Add a durable execution claim**

Do not rely only on Worker-local `.tasks` files. Add an idempotent claim event/state in the Controller Task service before ACK, or make ACK itself the single durable claim under the Task mutex. A duplicate executor that sees `ACKNOWLEDGED`, `RUNNING`, or a result must not launch the Skill again.

- [ ] **Step 5: Execute the manifest command safely**

Create private Task temp files with mode `0600`, pass a clean allowlist containing only required `PATH`, `HOME`, locale, and explicit Skill variables, enforce `timeoutSeconds` with an upper bound of 300, capture output with byte limits, and delete only temp files created by this invocation.

- [ ] **Step 6: Validate and publish the result**

Require valid JSON, validate against the declared output schema, sanitize the human summary, publish the artifact, and only then return completion. Map failures to public codes such as:

```text
TASK_INPUT_INVALID
SKILL_NOT_READY
SKILL_TIMEOUT
SKILL_EXECUTION_FAILED
SKILL_RESULT_MISSING
SKILL_RESULT_INVALID
```

- [ ] **Step 7: Lock Worker instructions**

The typed-task Skill must instruct the model to extract only a syntactically valid Task ID, call `hiclaw task execute` exactly once, and return bounded status. It must prohibit reconstructing input from Matrix, manually reading source into chat, writing artifacts itself, or retrying the command.

- [ ] **Step 8: Add the real Matrix wake-up integration**

The shell test registers and dispatches a deterministic Task to a running Worker, observes ACK/result, dispatches the same wake-up again, and proves an execution counter remains one.

- [ ] **Step 9: Defer commit until Task 7**

Intended verified commit:

```text
feat: execute versioned remote skills from typed tasks
```

---

### Task 6: Expose Fixed Fork and Protocol Identity

**Files:**
- Modify: `hiclaw-controller/internal/buildinfo/buildinfo.go`
- Modify: `hiclaw-controller/internal/buildinfo/buildinfo_test.go`
- Modify: `hiclaw-controller/internal/server/status_handler.go:64-74`
- Modify: `hiclaw-controller/internal/server/status_handler_test.go`
- Modify: `Makefile:21-105,163-205,311-448`
- Modify: `hiclaw-controller/Dockerfile:9-65`
- Modify: `manager/Dockerfile:13-87`
- Modify: `worker/Dockerfile:13-80`

**Interfaces:**
- `/api/v1/version` returns:

```json
{
  "upstreamTag": "v1.2.0-beta.1",
  "upstreamCommit": "78d0ceda336befa6e62bf89fc1a6b08b965e128d",
  "forkCommit": "<40-hex>",
  "patchDigest": "sha256:<64-hex>",
  "skillDistributionProtocolVersion": "1",
  "taskProtocolVersion": "1",
  "kubeMode": "embedded"
}
```

- OCI labels:

```text
org.opencontainers.image.revision
org.opencontainers.image.version
io.agentteams.upstream.revision
io.agentteams.patch.digest
io.agentteams.skill-distribution.version
io.agentteams.task-protocol.version
```

- Consumed by: Argus `agentteams/contract.lock.json` and A5/A8.

- [ ] **Step 1: Complete build-info tests first**

Test stable JSON names, exact upstream identity, release validation rejecting empty/development/unknown fields, and protocol version fields.

- [ ] **Step 2: Queue deferred RED command**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./internal/buildinfo ./internal/server -run 'BuildInfo|Version' -v
```

- [ ] **Step 3: Implement linker variables and release validation**

Local defaults may say `development`; release builds pass exact values via `-ldflags -X`. `ValidateRelease` requires 40-hex commits and `sha256:<64-hex>` patch digest.

- [ ] **Step 4: Compute one patch digest**

At build time, compute the digest from the committed diff against upstream SHA, excluding generated binaries, copied `hiclaw-controller/agent/`, test evidence, and temporary Docker contexts. The Make target must print the exact included file list before hashing.

- [ ] **Step 5: Pass identical identity into all images**

Controller compiles both binaries with the same linker values. Manager and Worker receive matching build args and OCI labels even though they copy `hiclaw` from the Controller image.

- [ ] **Step 6: Defer commit until Task 7**

Intended verified commit:

```text
build: expose Nacos runtime fork identity
```

---

### Task 7: Run the Unified Fork Gate, Commit Verified Units, and Capture Immutable Outputs

**Files:**
- Modify only owning files if verification exposes defects.
- Create no environment-specific evidence inside tracked source directories.

**Interfaces:**
- Produces: verified fork commit SHA, patch digest, Skill distribution protocol `1`, Task protocol `1`, and Controller/Manager/Worker image RepoDigests.
- Required by: `2026-08-03-argus-nacos-real-worker-integration.md`.

- [ ] **Step 1: Verify the unrelated installer remains untouched by this work**

Record, but do not alter:

```bash
git -C /e/heishou/AgentTeams-v1.2.0-beta.1 diff -- install/hiclaw-install.ps1
```

Compare it with the saved pre-existing BOM/AppService diff. If it contains any new hunk, stop and restore only the newly introduced hunk after user confirmation.

- [ ] **Step 2: Run all deferred focused tests**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./internal/executor -run 'SkillArchive|DigestSkillDirectory' -v
go test ./internal/oss/... -run 'ListObjects|MCFind' -v
go test ./internal/service -run 'RemoteSkillGeneration|PushRemoteSkills' -v
go test ./internal/task ./internal/server ./internal/auth ./internal/matrix ./cmd/hiclaw -run 'Task|Mention|BuildInfo|Version' -v
go test -race ./internal/task ./internal/service ./internal/server -v
cd ..
python -m unittest -v worker/scripts/test_remote_skills_sync.py
```

Expected: zero failures.

- [ ] **Step 3: Run full Go and Worker integration suites**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1/hiclaw-controller
go test ./... -v
go test -race ./internal/task ./internal/executor ./internal/service ./internal/server -v
cd ..
bash tests/test-remote-skills-generation.sh
bash tests/test-task-worker-execution.sh
make test
cd copaw && python -m pytest
```

Record each suite's collected/passed/failed/skipped counts separately.

- [ ] **Step 4: Fix failures only in the owning task**

For every defect, add or tighten the regression test first, then change the smallest owning file. Re-run the focused suite and then all suites from Step 3. After three failed fix attempts on the same issue, stop and report the blocker.

- [ ] **Step 5: Create the fork branch and verified commits**

Because the checkout started detached, create a branch from the current verified state:

```bash
git switch -c argus/nacos-task-runtime
```

Stage intentional files by explicit path groups. Never use `git add -A`; never stage `install/hiclaw-install.ps1`. Create verified commits corresponding to Tasks 1–6 using the intended messages. If the implementation cannot be cleanly separated without changing tested bytes, create one verified commit:

```text
feat: add Nacos skill runtime and typed tasks
```

- [ ] **Step 6: Build fixed local images**

```bash
cd /e/heishou/AgentTeams-v1.2.0-beta.1
make build-hiclaw-controller build-manager build-worker VERSION=v1.2.0-beta.1-argus.1
```

Inspect labels on all three images and require exact agreement.

- [ ] **Step 7: Push to the approved private/local registry and capture RepoDigests**

Use the registry configured for this AgentTeams environment. After push:

```bash
docker image inspect <controller-tag> --format '{{json .RepoDigests}}'
docker image inspect <manager-tag> --format '{{json .RepoDigests}}'
docker image inspect <worker-tag> --format '{{json .RepoDigests}}'
```

If push credentials or a registry target are unavailable, mark the dependent Argus plan BLOCKED. Do not substitute mutable image IDs.

- [ ] **Step 8: Record final identity and clean intentional status**

```bash
git status --short
git log -1 --oneline
git rev-parse HEAD
```

The only allowed remaining tracked diff is the pre-existing `install/hiclaw-install.ps1`. Record fork SHA, patch digest, RepoDigests, and protocol versions for Argus.
