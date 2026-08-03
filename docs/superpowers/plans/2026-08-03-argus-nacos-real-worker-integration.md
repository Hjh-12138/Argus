# Argus Nacos Skills and Real AgentTeams Worker Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish and lock eight self-contained Argus Skills in private Nacos, run formal headless audits through real AgentTeams Workers and typed Tasks, close real revision/recheck and leakage loops, and produce an automated A1–A8 acceptance report against the read-only current-source snapshot of `E:\heishou\koubo`.

**Architecture:** Argus records exact Nacos `source + name + version` coordinates, assigns them through AgentTeams `remoteSkills`, and waits for Controller/Worker observed readiness from the prerequisite fork plan. A ProjectDriver sends immutable source and role payloads through typed Tasks, validates machine artifacts, creates real revision/recheck Tasks, and unlocks Synth only after required evidence verifies. A recursive sanitizer and random-canary Project protect Matrix, MinIO, Worker filesystems, logs, reports, traces, and SQLite.

**Tech Stack:** Python 3.11+, standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `secrets`, `sqlite3`, `subprocess`, `tempfile`, `time`, `zipfile`), pytest 8+, private Nacos AI Registry via `npx @nacos-group/cli`, AgentTeams `remoteSkills`, Task protocol v1, Docker, Matrix, MinIO.

## Global Constraints

- Work in `E:\heishou\Argus v2`; `E:\heishou\koubo` is read-only and never cleaned, modified, staged, committed, executed, or used for dependency installation.
- Prerequisite: complete `2026-08-03-agentteams-nacos-task-runtime.md` and obtain fork SHA, patch digest, protocol versions, and immutable Controller/Manager/Worker RepoDigests.
- Deployment requires `ARGUS_NACOS_SOURCE=nacos://<private-host>/<namespace>` and `ARGUS_NACOS_AUTH_TYPE=sts-hiclaw|nacos|none`. If source, credentials, registry write permission, or immutable-version policy cannot be verified, the publication task is BLOCKED.
- Never publish Argus Skills to the default public AgentTeams market as a fallback.
- Private Nacos must reject overwriting an already published `name + version`.
- Formal audits use explicit versions only; no `latest`, empty version, or movable label.
- `skills.lock.json` records exactly eight unique `source + name + version` entries. Runtime directory digests are observed evidence, not user configuration.
- Every Worker reads the same immutable snapshot and validates its digest.
- Matrix carries bounded IDs only; source and raw secrets never enter Matrix messages.
- Four assessor, Meta, revision/recheck, and Synth machine artifacts are authoritative. `result.md` is human output only.
- A required Task failure, timeout, conflict, missing artifact, schema mismatch, or Skill identity mismatch cannot produce pass.
- The acceptance hallucination probe is allowed only under explicit `phase-one-acceptance` profile.
- Synthetic-secret uses a random per-run canary in a separate temporary fixture, never in `koubo`.
- Acceptance accepts any truthful gate for `koubo`; it verifies execution correctness, not a predetermined pass.
- 8/8 PASS is required for `phase_one=accepted`.
- Write tests before production changes, but do not execute test commands until Task 11. This preserves the user's explicit deferred-test decision from the interrupted session.
- Do not stage historical untracked documents or `__pycache__` directories. Stage explicit files only.

---

## File Structure

### New focused units

- `core/sanitizer.py` — recursive structured egress sanitizer.
- `core/workspace_snapshot.py` — Git-aware read-only current-source bundle.
- `agentteams/protocol.py` — strict Task request/record/result models.
- `agentteams/worker_payloads.py` — role-specific Task payloads and artifact references.
- `agentteams/project_driver.py` — register/dispatch/wait/reconcile/resume/revision/finalize DAG.
- `skills/publish_nacos.py` — validate exact Skill packages, publish new immutable versions, and write lock data only after registry verification.
- `acceptance/models.py` — A1–A8 report schemas.
- `acceptance/evidence.py` — sanitized command and digest evidence.
- `acceptance/leakage.py` — random-canary Project and bounded surface scanners.
- `acceptance/cleanup.py` — exact-manifest cleanup.
- `acceptance/phase_one.py` — unified A1–A8 command.

### Existing integration points

- `skills/` — four existing portable Skills plus four new assessor Skills.
- `skills/skills.lock.json` — exact Nacos coordinates, assignments, and publication evidence.
- `agents/*/identity.yaml` — Worker identity and required Skill coordinates.
- `agentteams/hiclaw_client.py` — Worker CR remoteSkills and typed Task CLI wrappers.
- `agentteams/orchestrator.py` — retain definitions/helpers; delegate real flow to `ProjectDriver`.
- `agentteams/contract.lock.json` — fixed fork/images/protocol identity.
- `cli/argus.py` — formal AgentTeams engine and acceptance commands.
- `core/{snapshot.py,report.py,tracing.py,redaction.py}` — hashing and egress integration.
- `README.md`, `docs/初赛-作品简介.md`, `docs/初赛-方案PPT大纲.md` — measured claims only.

---

### Task 1: Add the Shared Recursive Sanitizer

**Files:**
- Create: `core/sanitizer.py`
- Create: `tests/unit/test_sanitizer.py`
- Modify: `core/redaction.py`
- Modify: `core/tracing.py:65-81`
- Modify: `core/report.py` at final serialization
- Modify: `tests/security/test_leakage.py`

**Interfaces:**
- Produces: `Sanitizer(canaries: tuple[str, ...] = ())`.
- Produces: `sanitize(value: object) -> object`.
- Produces: `sanitize_text(text: str) -> str`.
- Produces: `contains_forbidden(value: object) -> bool`.
- Consumed by: Hiclaw client, ProjectDriver, Worker evidence, CLI errors, and acceptance evidence.

- [ ] **Step 1: Write recursive sanitizer tests first**

```python
def test_sanitizer_removes_nested_canary_and_private_fields():
    sanitizer = Sanitizer(canaries=("unique-canary",))
    got = sanitizer.sanitize({
        "message": "token=unique-canary",
        "nested": [{"raw_prompt": "hidden", "ok": "prefix unique-canary suffix"}],
    })
    text = json.dumps(got)
    assert "unique-canary" not in text
    assert "raw_prompt" not in text
    assert "[REDACTED]" in text
```

Add tuples, exception strings, token patterns under allowed keys, bytes rejection, unsupported objects, scalar bounds, and ordinary unchanged text.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/unit/test_sanitizer.py -v
```

- [ ] **Step 3: Implement recursive key and value sanitization**

Forbid case-insensitive keys:

```text
private_reasoning
reasoning_text
raw_prompt
raw_response
source_code
secret
api_key
```

Reuse token patterns from `core.redaction`; never use `repr()` on arbitrary objects at egress.

- [ ] **Step 4: Apply at trace and report boundaries**

Sanitize trace scalar strings after allowlisting. Sanitize the entire report dict immediately before JSON/Markdown materialization.

- [ ] **Step 5: Queue regression suite and defer commit**

```powershell
python -m pytest tests/unit/test_sanitizer.py tests/unit/test_tracing.py tests/unit/test_report.py tests/security/test_leakage.py -v
```

Intended verified commit: `feat: sanitize all structured egress`.

---

### Task 2: Build a Read-Only Current-Source Snapshot Bundle

**Files:**
- Create: `core/workspace_snapshot.py`
- Create: `tests/unit/test_workspace_snapshot.py`
- Modify: `core/snapshot.py`
- Modify: `core/schemas.py`

**Interfaces:**
- Produces: `WorkspaceSnapshotBuilder(excludes: tuple[str, ...] = DEFAULT_EXCLUDES)`.
- Produces: `build(target: Path, output_zip: Path) -> WorkspaceBundle`.
- `WorkspaceBundle` fields: `snapshot`, `coverage`, `included`, `excluded`, `deleted`, `archive_path`, `archive_sha256`.
- Consumed by: ProjectDriver, A4, and leakage fixture setup.

- [ ] **Step 1: Write Git-aware snapshot tests first**

Create a temporary Git repo containing tracked modifications, untracked source, a deleted tracked file, `node_modules`, cache files, a diagnostic profile, PNG, and MP4. Assert current source inclusion, exact exclusion reasons, deletion records, deterministic ZIP inventory/timestamps, and post-build workspace mutations not changing the bundle.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/unit/test_workspace_snapshot.py -v
```

- [ ] **Step 3: Implement read-only inventory**

Use only:

```text
git -C <target> ls-files -z
git -C <target> status --porcelain=v1 -z --untracked-files=all
```

Never call checkout, clean, add, reset, build, install, or target code.

- [ ] **Step 4: Apply exact exclusion policy**

Implement the patterns from the approved spec and record one reason per excluded path. Resolve paths and reject symlink escapes.

- [ ] **Step 5: Share hashing/language logic with SnapshotBuilder**

Extract focused helpers rather than duplicating file hashing. Preserve existing Demo snapshot behavior.

- [ ] **Step 6: Queue regressions and defer commit**

```powershell
python -m pytest tests/unit/test_workspace_snapshot.py tests/unit/test_snapshot.py tests/unit/test_preflight.py -v
```

Intended verified commit: `feat: snapshot current source workspaces`.

---

### Task 3: Make the Existing Four Skills Self-Contained

**Files:**
- Modify: `skills/argus-finding-emit/**`
- Modify: `skills/argus-evidence-verify/**`
- Modify: `skills/argus-release-policy-evaluate/**`
- Modify: `skills/argus-report-materialize/**`
- Create: `tests/contract/test_skill_subprocess_contracts.py`

**Interfaces:**
- Executable contract: `python implementation/main.py --input <json> --output <json>`.
- Exit 0 with schema-valid output; exit 2 with schema-valid error artifact.
- No imports from host-only `core.*`, `agents.*`, or `agentteams.*`.
- Manifest execution stanza:

```yaml
execution:
  command: ["python", "implementation/main.py"]
  input: json-file
  output: json-file
  timeoutSeconds: 300
```

- Consumed by: Nacos publication and real Worker Task execution.

- [ ] **Step 1: Write isolated-copy subprocess tests first**

Copy each Skill directory into an empty temp root, clear `PYTHONPATH`, run success and invalid input, validate output against bundled schema, and scan imports.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/contract/test_skill_subprocess_contracts.py -v
```

- [ ] **Step 3: Move only required deterministic logic into each package**

Use plain dict/JSON conversion. Do not copy unrelated Argus modules. Report materialization may write only beneath the output directory declared in input.

- [ ] **Step 4: Align schemas and manifests**

All object schemas set `additionalProperties: false`. Error output has stable public codes and no raw exception or secret fields.

- [ ] **Step 5: Queue contracts and defer commit**

```powershell
python -m pytest tests/contract/test_skill_contracts.py tests/contract/test_skill_subprocess_contracts.py -v
```

Intended verified commit: `refactor: make core audit skills portable`.

---

### Task 4: Add Four Self-Contained Assessor Skills

**Files:**
- Create: `skills/argus-dependency-inspect/**`
- Create: `skills/argus-code-rule-scan/**`
- Create: `skills/argus-secret-scan/**`
- Create: `skills/argus-ci-policy-check/**`
- Create: `tests/contract/test_assessor_skill_contracts.py`

**Interfaces:**
- Common input: `schema_version`, `run_id`, `snapshot_id`, `source_root`, `files[{path,sha256,size,language}]`, and role-specific fixtures.
- Output: schema-valid `AgentResult` with `status`, `agent`, `input_snapshot_id`, and `findings`.
- `argus-code-rule-scan` accepts `acceptance_probe` only under `profile == "phase-one-acceptance"`.

- [ ] **Step 1: Write isolated golden fixture tests first**

Required categories:

```text
argus-dependency-inspect → dependency.nonexistent
argus-code-rule-scan     → code.placeholder
argus-secret-scan        → security.sql_injection and redacted hardcoded secret
argus-ci-policy-check    → delivery.test_gap
```

Add vulnerable/fixed fixtures and acceptance-probe rejection outside the acceptance profile.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/contract/test_assessor_skill_contracts.py -v
```

- [ ] **Step 3: Port dependency and delivery rules**

Copy only deterministic parsing from `agents/dep/detector.py` and `agents/delivery/detector.py`. Registry evidence is typed input, never a network call.

- [ ] **Step 4: Port code and security rules**

Copy focused patterns from `agents/code/detector.py` and `agents/sec/detector.py`. Secret evidence stores redacted display and HMAC only.

- [ ] **Step 5: Queue all eight contracts and defer commit**

```powershell
python -m pytest tests/contract/test_assessor_skill_contracts.py tests/contract/test_skill_subprocess_contracts.py -v
```

Intended verified commit: `feat: add portable assessor skills`.

---

### Task 5: Publish and Lock Eight Skills in Private Nacos

**Files:**
- Create: `skills/publish_nacos.py`
- Create: `tests/unit/test_publish_nacos.py`
- Modify: `skills/skills.lock.json`
- Modify: `agents/dep/identity.yaml`
- Modify: `agents/code/identity.yaml`
- Modify: `agents/sec/identity.yaml`
- Modify: `agents/delivery/identity.yaml`
- Modify: `agents/meta/identity.yaml`
- Modify: `agents/synth/identity.yaml`
- Modify: `tests/unit/test_agentteams_skill_lock.py`

**Interfaces:**
- CLI:

```text
python skills/publish_nacos.py --source "$ARGUS_NACOS_SOURCE" --auth-type "$ARGUS_NACOS_AUTH_TYPE" --version 1.0.0 --verify-only
python skills/publish_nacos.py --source "$ARGUS_NACOS_SOURCE" --auth-type "$ARGUS_NACOS_AUTH_TYPE" --version 1.0.0 --publish
```

- Produces lock schema:

```json
{
  "schema_version": "2",
  "source": "nacos://host/namespace",
  "auth_type": "sts-hiclaw",
  "skills": [{"name": "argus-secret-scan", "version": "1.0.0", "local_sha256": "..."}],
  "assignments": {"argus-sec": ["argus-secret-scan", "argus-finding-emit"]}
}
```

- The publication script must query installed Nacos CLI help/version and use the supported draft/upload/review/release commands discovered from that CLI. It may not invent command flags.
- Consumed by: Orchestrator Worker CR generation and A5.

- [ ] **Step 1: Write publication command-builder tests first**

Use a fake subprocess runner to assert:

- missing source/version blocks before invocation;
- all eight directories validate;
- source must be private configured source, not the default market;
- verify-only fetches exact versions into a temp root and compares complete contents;
- publish refuses if the exact version already exists with different content;
- lock file writes only after all eight versions verify remotely;
- no credentials appear in command evidence or errors.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/unit/test_publish_nacos.py tests/unit/test_agentteams_skill_lock.py -v
```

- [ ] **Step 3: Implement local package validation and deterministic archive creation**

Require `SKILL.md`, manifest execution, schemas, and implementation for all eight Skills. Exclude caches and normalize text line endings only if Nacos publication tooling preserves the normalized bytes. Record local directory digest as evidence.

- [ ] **Step 4: Implement CLI capability discovery**

Run:

```text
npx @nacos-group/cli --version
npx @nacos-group/cli skill --help
npx @nacos-group/cli skill-release --help
```

or the actual installed command forms. Parse only exit status and bounded help text. If no publish/release capability exists, stop BLOCKED and request the approved registry publication method.

- [ ] **Step 5: Publish exact immutable versions**

Use a fresh semantic version agreed for all eight Skills, initially `1.0.0` unless that version already exists. The registry must reject overwrite. If any version exists, verify bytes; identical is idempotent, different is BLOCKED and requires a new version.

- [ ] **Step 6: Fetch back and verify all releases before writing lock**

Download each exact version into an isolated temp root, validate its complete directory, and compare digest with the local package. Only then atomically write `skills.lock.json`.

- [ ] **Step 7: Update identities and assignments**

Use the approved six-Worker mapping. Identity required Skills reference names; source/version come from the lock. Ensure exactly eight unique coordinates.

- [ ] **Step 8: Defer commit until Task 11**

Intended verified commit: `feat: publish and lock eight Nacos skills`.

---

### Task 6: Add Strict AgentTeams Task Protocol Client Wrappers

**Files:**
- Create: `agentteams/protocol.py`
- Create: `tests/unit/test_agentteams_protocol.py`
- Modify: `agentteams/hiclaw_client.py`
- Modify: `agentteams/contract.lock.json`
- Modify: `tests/contract/test_agentteams_contract.py`

**Interfaces:**
- Produces: `TaskState`, `TaskEnvelope`, `TaskRecord`, `TaskResultRef` dataclasses/enums.
- Produces:

```python
register_task(request: dict) -> TaskRecord
dispatch_task(task_id: str, expected_revision: int) -> TaskRecord
get_task(task_id: str) -> TaskRecord
ack_task(task_id: str, expected_revision: int) -> TaskRecord
start_task(task_id: str, expected_revision: int) -> TaskRecord
terminal_task(task_id: str, expected_revision: int, state: str, reason: str) -> TaskRecord
wait_task(task_id: str, terminal: set[TaskState], timeout_s: int) -> TaskRecord
get_worker_skill_observation(worker: str) -> dict
```

- Replaces: `apply_worker_package`; Worker configuration uses `remoteSkills` in YAML/JSON apply payload.
- Consumed by: ProjectDriver.

- [ ] **Step 1: Write parser and subprocess-stub tests first**

Test malformed JSON, unknown state, missing revision, bad SHA, absolute/result paths, timeout, sanitized CLI errors, and strict Worker observed state.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/unit/test_agentteams_protocol.py tests/contract/test_agentteams_contract.py -v
```

- [ ] **Step 3: Implement strict models and parsing**

Reject unknown keys where the protocol is fixed. Result refs must remain beneath `tasks/<task-id>/`.

- [ ] **Step 4: Implement temporary-file CLI wrappers**

Use existing `_run`; pass registration JSON through private temporary files copied into the Manager/Controller container only when needed, then delete only created files. Poll with `time.monotonic()` and bounded intervals.

- [ ] **Step 5: Replace package upload with `remoteSkills` Worker apply**

Build Worker resources containing one source/auth group and exact name/version entries from `skills.lock.json`. Never pass Argus names through built-in `--skills`. Wait for observed generation and every assigned Skill `ready=true`.

- [ ] **Step 6: Populate contract lock from prerequisite outputs**

Write upstream/fork/patch/protocol/image RepoDigests. If any immutable RepoDigest is unavailable, stop BLOCKED.

- [ ] **Step 7: Defer commit until Task 11**

Intended verified commit: `feat: add typed AgentTeams task client`.

---

### Task 7: Implement ProjectDriver for Real Assessor DAGs

**Files:**
- Create: `agentteams/worker_payloads.py`
- Create: `agentteams/project_driver.py`
- Create: `tests/unit/test_project_driver.py`
- Modify: `agentteams/orchestrator.py`
- Modify: `tests/unit/test_agentteams_orchestrator.py`
- Modify: `tests/unit/test_agentteams_results.py`

**Interfaces:**
- Produces: `ProjectDriver(client, workspace, *, ack_timeout_s=60, run_timeout_s=300)`.
- Produces: `run(request: dict, bundle: WorkspaceBundle) -> ProjectOutcome`.
- Produces: `resume(project_id: str) -> ProjectOutcome`.
- `ProjectOutcome`: project ID, status, Task records, policy/report refs, gate.

- [ ] **Step 1: Write fake-client DAG tests first**

Assert exact sequence: register four assessor Tasks, dispatch, wait ACK/terminal, validate artifacts, register Meta, then Synth. Test resume, duplicate reconciliation, required failure, missing artifact, and no pass on invalid Skill observation.

- [ ] **Step 2: Queue deferred RED command**

```powershell
python -m pytest tests/unit/test_project_driver.py -v
```

- [ ] **Step 3: Build role-specific payloads**

Assessor inputs reference the immutable snapshot and role-only fixtures. Meta references four artifact paths/digests. Synth references reviewed artifacts and policy input. Matrix never receives source.

- [ ] **Step 4: Implement register/dispatch/reconcile**

Use one immutable `project_id`, persist Project metadata, enforce ACK timeout and one same-attempt retry, enforce run timeout, and never start a concurrent duplicate after ACK.

- [ ] **Step 5: Validate machine artifacts before unlock**

Check agent, snapshot, required status, Skill name/version/generation, schema, and upstream digests. Require both typed artifact and human summary for formal completion.

- [ ] **Step 6: Delegate old Orchestrator execution to ProjectDriver**

Retain Worker definitions and public compatibility helpers. Remove mock file-based Task completion claims from the formal path.

- [ ] **Step 7: Queue regressions and defer commit**

```powershell
python -m pytest tests/unit/test_project_driver.py tests/unit/test_agentteams_results.py tests/unit/test_agentteams_orchestrator.py -v
```

Intended verified commit: `feat: drive real AgentTeams audit projects`.

---

### Task 8: Implement Real Revision/Recheck and Formal AgentTeams CLI Engine

**Files:**
- Modify: `agentteams/project_driver.py`
- Modify: `agentteams/orchestrator.py`
- Modify: `cli/argus.py`
- Modify: `core/report.py`
- Create: `tests/integration/test_agentteams_revision_live.py`
- Create: `tests/integration/test_cli_agentteams_live.py`
- Modify: `tests/integration/test_agentteams_e2e.py`
- Modify: `tests/integration/test_cli_e2e.py`

**Interfaces:**
- CLI: `--engine {agentteams,local}`; formal `audit --headless` default is `agentteams`.
- Reports include `execution_engine`.
- ProjectDriver handles `REVISION_NEEDED`, real revision Task, `meta-recheck-N`, Synth dependency replacement, and `REVISION_RESOLVED`.

- [ ] **Step 1: Write revision and CLI behavior tests first**

Test parser default, explicit local mode, report engine, required failure → unknown, and live completion. Live revision test asserts real MinIO Task directories, real Worker artifacts, Synth pending before recheck, hallucination metric 1, probe absent from final findings, and Project completed.

- [ ] **Step 2: Queue deferred RED commands**

```powershell
python -m pytest tests/integration/test_cli_e2e.py tests/integration/test_cli_agentteams_live.py -v
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/integration/test_agentteams_revision_live.py -v -m agentteams
```

- [ ] **Step 3: Implement revision parsing and Task creation**

Require finding ID, `HALLUCINATION`, public reason code, and `revision_for`. Never carry private reasoning.

- [ ] **Step 4: Relock Synth and enforce revision cap**

Replace Synth dependency immediately with recheck. Maximum two revisions per original Task; third request → `human-wait`.

- [ ] **Step 5: Split CLI local and AgentTeams paths**

Move current deterministic logic into `_audit_local`. `_audit_agentteams` builds the immutable bundle, calls ProjectDriver, validates final artifacts, sanitizes local copies, and maps gate to exit code.

- [ ] **Step 6: Queue live suites and defer commit**

```powershell
python -m pytest tests/integration/test_cli_e2e.py -v
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/integration/test_agentteams_revision_live.py tests/integration/test_cli_agentteams_live.py tests/integration/test_agentteams_e2e.py -v -m agentteams
```

Intended verified commit: `feat: run headless audits on real AgentTeams tasks`.

---

### Task 9: Add Random-Canary Distributed Leakage E2E

**Files:**
- Create: `acceptance/__init__.py`
- Create: `acceptance/evidence.py`
- Create: `acceptance/leakage.py`
- Create: `tests/security/test_leakage_live.py`
- Modify: `agentteams/hiclaw_client.py`
- Modify: `tests/security/test_leakage.py`

**Interfaces:**
- Produces: `run_leakage_e2e(client, temp_root: Path) -> LeakageEvidence`.
- Bounded wrappers: Matrix Project events, exact MinIO prefixes, Worker Task files, allowlisted logs.
- Evidence contains per-surface counts/digests only.

- [ ] **Step 1: Write live random-canary test first**

Generate `secrets.token_urlsafe(32)`, build a temporary source fixture, execute a real security Project, assert a redacted/HMAC Finding and zero raw canary outside the exact source fixture.

- [ ] **Step 2: Queue deferred RED command**

```powershell
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/security/test_leakage_live.py -v -m agentteams
```

- [ ] **Step 3: Implement bounded readers**

Read exact Project/task Matrix and MinIO scopes, six Worker logs, Manager/Controller logs, local stdout/stderr/report/trace/SQLite. Never collect full `docker inspect`; allow name/status/image digest metadata only.

- [ ] **Step 4: Implement streaming scanner**

Scan chunks without persisting sensitive content. Record surface, sanitized path, and HMAC on a hit. Exclude the source fixture by exact file path.

- [ ] **Step 5: Sanitize every client error and egress path**

Apply Task 1 sanitizer to Matrix sends, MinIO helpers, Docker errors, reports, and evidence. Include a contaminated ordinary `message` field to prove value filtering.

- [ ] **Step 6: Queue local/live suites and defer commit**

```powershell
python -m pytest tests/security/test_leakage.py -v
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/security/test_leakage_live.py -v -m agentteams
```

Intended verified commit: `test: verify distributed audit leakage boundary`.

---

### Task 10: Implement Acceptance, Exact Cleanup, and Measured Documentation

**Files:**
- Create: `acceptance/models.py`
- Create: `acceptance/phase_one.py`
- Create: `acceptance/cleanup.py`
- Create: `tests/unit/test_acceptance_report.py`
- Create: `tests/integration/test_phase_one_acceptance_live.py`
- Modify: `cli/argus.py`
- Modify: `README.md`
- Modify: `docs/初赛-作品简介.md`
- Modify: `docs/初赛-方案PPT大纲.md`
- Create: `tests/contract/test_preliminary_docs.py`

**Interfaces:**
- CLI:

```powershell
argus acceptance phase-one --target "E:\heishou\koubo" --workspace-mode current-source --agentteams-live --acceptance-probe hallucination-revision --leakage-e2e
argus acceptance cleanup --run-id <id>
```

- Output: `.argus/acceptance/<run-id>/{acceptance.json,acceptance.md,evidence-manifest.json,command-results/,sanitized-excerpts/}`.

- [ ] **Step 1: Write report and cleanup tests first**

Assert exactly A1–A8; 8/8 PASS accepted; any FAIL/BLOCKED not accepted; no duplicate suite count; cleanup resources exact; paths outside the run root and unowned remote IDs rejected.

- [ ] **Step 2: Write docs contract first**

Require explicit private Nacos governance, Worker local execution, AI gateway's actual model/MCP boundary, six Workers, eight unique versions, live acceptance command, read-only target, and no package-v2 or cloud-Skill execution claim. Intro remains ≤500 non-whitespace characters.

- [ ] **Step 3: Queue deferred RED commands**

```powershell
python -m pytest tests/unit/test_acceptance_report.py tests/contract/test_preliminary_docs.py -v
```

- [ ] **Step 4: Implement A1–A8 orchestration**

Record each suite separately. A2/A4/A7 use real AgentTeams. A5 checks exact Nacos coordinates and observed readiness. A8 validates docs against measured evidence.

- [ ] **Step 5: Implement sanitized evidence and exact cleanup**

Store command, exit, duration, counts, artifact digests, bounded excerpts, and exact resource ownership. Default remote retention 24 hours; cleanup explicit.

- [ ] **Step 6: Update docs only after evidence fields exist**

Remove claims exceeding measured results. Explain that Nacos governs Skills while Higress governs models/MCP/credentials.

- [ ] **Step 7: Queue live command test and defer commit**

```powershell
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/integration/test_phase_one_acceptance_live.py -v -m agentteams
```

Intended verified commits:

```text
feat: automate phase one acceptance
docs: align preliminary claims with live evidence
```

---

### Task 11: Run Unified Verification, Commit Verified Units, and Execute A1–A8

**Files:**
- Modify only owning task files if verification exposes defects.
- Generated evidence stays under `.argus/acceptance/<run-id>/` and is not committed unless sanitized stable summaries are required.

**Interfaces:**
- Produces final acceptance report, Project IDs, test counts, evidence path, and retention deadline.

- [ ] **Step 1: Verify prerequisites and target baseline**

Require `ARGUS_NACOS_SOURCE`, successful exact-version fetch for all eight Skills, contract lock RepoDigests, and healthy AgentTeams containers. Record `koubo` status and its hash without modifying it.

- [ ] **Step 2: Run all deferred local suites**

```powershell
python -m pytest tests/unit tests/contract tests/security/test_leakage.py tests/integration/test_cli_e2e.py -v
```

Expected: zero failures; record skips separately.

- [ ] **Step 3: Run all live AgentTeams suites**

```powershell
$env:ARGUS_AGENTTEAMS_E2E='1'
python -m pytest tests/integration/test_agentteams_e2e.py tests/integration/test_agentteams_revision_live.py tests/integration/test_cli_agentteams_live.py tests/security/test_leakage_live.py tests/integration/test_phase_one_acceptance_live.py -v -m agentteams
```

Expected: zero failures.

- [ ] **Step 4: Fix failures in owning tasks only**

Add/tighten regression tests before each fix. Re-run focused and full suites. Stop after three failed fix attempts on the same issue.

- [ ] **Step 5: Create verified commits**

Stage explicit files only. Do not add historical plans/specs or caches. Create the intended Task 1–10 commits, or combine inseparable tested units without changing tested bytes.

- [ ] **Step 6: Run unified A1–A8 command**

```powershell
argus acceptance phase-one `
  --target "E:\heishou\koubo" `
  --workspace-mode current-source `
  --agentteams-live `
  --acceptance-probe hallucination-revision `
  --leakage-e2e
```

Exit 0 only when A1–A8 all PASS.

- [ ] **Step 7: Verify `koubo` remains untouched**

Capture after-status and compare with baseline. If concurrent user changes occurred, distinguish them using snapshot manifests/timestamps. Never reset the target.

- [ ] **Step 8: Inspect final report invariants**

Require:

```text
phase_one = accepted
A1..A8 = PASS
execution_engine = agentteams for A2/A4/A7
koubo project status = completed
hallucination metric = 1 and probe absent from findings
locked unique Nacos skills = 8
all assigned skills observed ready
all leakage surface counts = 0
```

- [ ] **Step 9: Report immutable evidence**

Report acceptance run ID, Project IDs, eight `source+name+version` coordinates, fork/image RepoDigests, separate test suite counts, evidence path, and 24-hour retention deadline. If any invariant fails, report `DONE_WITH_CONCERNS` or `BLOCKED`, never accepted.
