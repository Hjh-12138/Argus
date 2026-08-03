# Argus Private Nacos Skill Governance and Local Worker Execution Design

**Date:** 2026-08-03  
**Status:** Approved design  
**Supersedes:** The Skill-distribution portions of `2026-08-03-argus-agentteams-phase-one-closure-design.md`  
**Does not supersede:** The generic AgentTeams Task/ACK protocol, real revision/recheck loop, leakage boundary, or A1–A8 acceptance gate

## 1. Goal

Use AgentTeams' existing private-Nacos `remoteSkills` path to govern and distribute eight Argus Skills, while preserving local execution inside real AgentTeams Workers against a read-only source snapshot.

The design must:

- use private Nacos AI Registry for Skill publishing, immutable versioning, access control, and distribution;
- use AgentTeams Worker/Team CRDs to assign exact Skill versions;
- execute deterministic Skill code inside AgentTeams Workers, not in a cloud Skill runtime;
- retain AgentTeams Matrix, MinIO, Worker lifecycle, Team/DAG, AI gateway, MCP, and consumer-isolation capabilities;
- retain a generic Task/ACK state service for reliable one-shot execution and typed results;
- close the real hallucination → revision → recheck → Synth loop;
- produce an automated A1–A8 phase-one acceptance report;
- avoid a second custom Skill registry or package protocol.

## 2. Final Decisions

### 2.1 Skill control plane

Private Nacos AI Registry is the only registry for Argus Skills.

Each formal audit references a Skill by explicit immutable coordinates:

```text
source + name + version
```

The private Nacos deployment must reject overwriting an already published `name + version`. Formal Argus audits must not use an unversioned reference, `latest`, or any movable label.

A directory digest is computed automatically after download and again after Worker activation. It is runtime evidence, not a user-supplied `remoteSkills` field and not a second version system.

### 2.2 Execution location

All eight Argus Skills execute locally inside AgentTeams Workers. Source snapshots do not move to Function Compute AgentRun, a cloud Sandbox, or a remote Skill execution service.

### 2.3 AI gateway boundary

AgentTeams' built-in Higress AI gateway continues to govern:

- model routes and providers;
- Manager/Worker consumers;
- MCP Server authorization;
- real credential isolation;
- route, timeout, rate, and invocation observability.

It does not store, version, distribute, activate, or execute Agent Skill directories. Skill governance belongs to Nacos AI Registry plus the AgentTeams Controller/MinIO/Worker distribution path.

### 2.4 Removed design direction

Do not add or retain a parallel Worker package manifest v2 Skill-governance path.

The following experimental direction is superseded:

- `manifest.version == 2` as an Argus Skill registry contract;
- `managed_artifacts` declarations in Worker packages;
- a package-specific generation protocol separate from `remoteSkills`;
- `managed-artifacts-sync.py` as an independent Worker Skill convergence loop.

Existing unrelated package behavior remains unchanged. Legacy packages retain their current seed-only semantics.

### 2.5 Retained AgentTeams extension

Retain the generic MinIO-backed Task/ACK protocol because Skill distribution and Task execution solve different problems.

- `remoteSkills` answers: "Which Skill bytes are available to this Worker?"
- Task/ACK answers: "Which immutable input should this Worker process once, under what deadline and idempotency key, and where is the authoritative result?"

AgentTeams must not contain Argus-specific finding, policy, revision, or gate semantics.

## 3. Component Responsibilities

## 3.1 Argus

Argus owns:

- publishing or verifying the eight versioned Skill releases in private Nacos;
- `skills.lock.json` with exactly eight unique `source + name + version` entries;
- building a read-only immutable current-source snapshot;
- creating six Worker identities and their exact `remoteSkills` assignments;
- creating and reconciling the audit Project DAG;
- registering assessor, Meta, revision, recheck, and Synth Tasks;
- validating Task state, active Skill identity, input references, typed artifacts, and upstream artifact references;
- enforcing required-task failure semantics;
- materializing sanitized reports and acceptance evidence;
- orchestrating A1–A8.

## 3.2 Private Nacos AI Registry

Nacos owns:

- Skill upload and publication;
- review and access control;
- immutable `name + version` publication;
- serving complete Skill archives through the existing Nacos Skills API;
- retaining published versions required by locked Argus runs.

Every Argus Skill archive contains a self-contained Agent Skill directory:

```text
<skill-name>/
├── SKILL.md
├── manifest.yaml
├── schemas/
│   ├── input.schema.json
│   └── output.schema.json
└── implementation/
    └── main.py
```

Additional schema or reference files are allowed when declared by the Skill contract. ZIP is only the Nacos transport container. The semantic unit is the extracted Agent Skill directory.

## 3.3 AgentTeams Controller

The Controller owns:

- parsing Worker/Team CRD `remoteSkills` declarations;
- requiring an explicit version for formal Argus assignments;
- downloading the requested Skill through the existing `NacosAIClient.GetSkill` path;
- safely extracting archives and rejecting traversal, symlinks, special files, and invalid layouts;
- computing a canonical directory digest over sorted relative paths and file bytes;
- staging a complete multi-Skill generation under a temporary MinIO prefix;
- independently re-reading the staged generation and verifying its digest;
- publishing one desired-generation pointer only after every assigned Skill verifies;
- exposing generic Task register/get/dispatch/ack/start/result/terminal APIs;
- persisting Task state and typed artifacts before sending Matrix wake-ups;
- reporting fixed fork and protocol identity through `/api/v1/version`.

## 3.4 AgentTeams Worker

A Worker owns:

- polling or reacting to its desired Skill generation;
- downloading the full generation into a private staging directory;
- independently computing each Skill directory digest;
- atomically activating the complete assigned Argus Skill set;
- rolling back the entire set if any activation or post-activation check fails;
- writing observed state containing `name`, `version`, `observed_digest`, and `ready`;
- handling a Matrix `ARGUS_TYPED_TASK` wake-up through the locked `typed-task-execution` Skill;
- calling `hiclaw task execute --id <task-id> -o json` exactly once per wake-up;
- validating assignment, deadline, attempt, input digests, active Skill name/version, and idempotency key before ACK;
- executing the Skill with bounded time, a clean allowlisted environment, and JSON files;
- publishing one typed machine artifact plus a bounded human `result.md`.

## 3.5 MinIO

MinIO is the authoritative storage plane for:

- immutable source snapshot bundles;
- staged and active Skill generation metadata;
- Worker observed Skill state;
- Task immutable requests and dispatch envelopes;
- append-only Task events;
- typed artifacts and human summaries;
- Project metadata and acceptance evidence.

Matrix is not an authoritative storage plane.

## 3.6 Matrix

Matrix is used only for:

- bounded Worker wake-ups;
- visible collaboration and human supervision;
- public Task/Project status notifications.

A typed wake-up contains only:

```text
ARGUS_TYPED_TASK task_id=<id> envelope=tasks/<id>/dispatch/envelope.json @<worker>:<domain>
```

It must not contain source, Task input payloads, secrets, raw findings, private reasoning, or raw exceptions.

## 4. Skill Inventory and Assignment

The locked global inventory contains exactly eight unique Skills:

1. `argus-dependency-inspect`
2. `argus-code-rule-scan`
3. `argus-secret-scan`
4. `argus-ci-policy-check`
5. `argus-finding-emit`
6. `argus-evidence-verify`
7. `argus-release-policy-evaluate`
8. `argus-report-materialize`

Recommended Worker assignments:

| Worker | Assigned Skills |
|---|---|
| Dep | `argus-dependency-inspect`, `argus-finding-emit` |
| Code | `argus-code-rule-scan`, `argus-finding-emit` |
| Sec | `argus-secret-scan`, `argus-finding-emit` |
| Delivery | `argus-ci-policy-check`, `argus-finding-emit` |
| Meta | `argus-evidence-verify`, `argus-finding-emit` |
| Synth | `argus-release-policy-evaluate`, `argus-report-materialize` |

A Skill may be assigned to multiple Workers, but `skills.lock.json` counts each `source + name + version` once.

Each Worker CR uses the existing shape:

```yaml
spec:
  remoteSkills:
    - source: nacos://<private-registry>/<argus-namespace>
      authType: sts-hiclaw
      skills:
        - name: argus-secret-scan
          version: 1.0.0
```

No Argus Skill is declared through `spec.skills`; that field remains for AgentTeams built-in Skills.

## 5. Canonical Directory Digest

The Controller and Worker use the same deterministic digest algorithm:

1. enumerate regular files recursively;
2. convert relative paths to POSIX form;
3. sort paths bytewise;
4. for each path, hash:

```text
relative-path + NUL + file-bytes + NUL
```

5. encode as `sha256:<hex>`.

The digest proves downloaded, staged, and activated bytes agree. The immutable Nacos version remains the release identity. The digest is recorded in:

- Controller generation metadata;
- Worker observed state;
- Task execution evidence;
- final acceptance evidence.

A digest mismatch is a deployment or runtime integrity failure. It does not create a new version.

## 6. Skill Distribution and Atomic Activation

## 6.1 Controller generation flow

For one Worker reconciliation:

1. validate every remote Skill has `name` and explicit `version`;
2. fetch every Skill into a fresh private temporary root;
3. validate archive safety and required Skill structure;
4. compute each canonical directory digest;
5. create a deterministic generation identity from sorted `source + name + version + digest` entries;
6. upload all Skill files under:

```text
agents/<worker>/.skills/generations/<generation>/skills/<name>/...
```

7. re-list and re-read the complete staged generation;
8. recompute every directory digest;
9. write `descriptor.json` containing all Skill coordinates and digests;
10. atomically update:

```text
agents/<worker>/.skills/desired.json
```

The previous desired generation remains untouched until step 10.

## 6.2 Worker activation flow

The Worker:

1. reads `desired.json`;
2. skips work if the same generation is already fully observed and ready;
3. downloads the complete generation into `.skills/staging/<generation>`;
4. verifies all expected files and digests;
5. acquires one activation lock;
6. moves all currently managed Argus Skill directories to a rollback root;
7. activates all new directories;
8. recomputes active digests;
9. writes local and MinIO `observed.json` only after all Skills verify;
10. removes rollback data only after at least one Task successfully executes on the new generation, or according to a bounded retention policy after acceptance.

A failure at steps 6–9 restores every prior managed directory. Unmanaged built-in, Manager-pushed, user, or runtime Skill directories are not touched.

## 6.3 Removal semantics

Removing a Skill from `remoteSkills` removes only that Controller-managed remote Skill during the next successful generation activation.

It must not remove:

- AgentTeams built-in Skills;
- Manager-owned on-demand Skills;
- Worker runtime files;
- unrelated user directories.

Ownership is derived from the previous observed generation, not from a broad `skills/**` deletion.

## 7. Task/ACK Protocol

## 7.1 State model

States are exactly:

```text
REGISTERED
DISPATCHED
ACKNOWLEDGED
RUNNING
COMPLETED
REVISION_NEEDED
BLOCKED
FAILED
TIMED_OUT
CONFLICT
```

State never moves backward. Every mutation supplies the expected revision. Controller serializes per-Task mutations in the phase-one single-Controller deployment.

## 7.2 Task storage layout

```text
tasks/<task-id>/
├── meta.json
├── base/
│   └── request.json
├── dispatch/
│   └── envelope.json
├── artifacts/
│   └── result.json
├── result.md
└── events/
    ├── 0000000001.json
    └── ...
```

## 7.3 Envelope fields

A Task envelope includes:

- schema version;
- Task and Project IDs;
- assigned Worker;
- Task kind;
- attempt and deadline;
- Skill name and immutable Nacos version;
- active Skill observation/generation reference;
- input artifact paths and SHA-256 digests;
- bounded JSON input payload;
- output schema path;
- agent version;
- idempotency key.

## 7.4 Reliable dispatch

1. Manager/Argus registers the Task.
2. Controller writes the immutable request, envelope, Task record, and event.
3. Dispatch transitions to `DISPATCHED` before Matrix send.
4. Controller sends one structured full mention.
5. On Matrix failure or ACK timeout, the same attempt and idempotency key may be dispatched once more.
6. A second ACK timeout transitions to `TIMED_OUT`.
7. After ACK, no concurrent duplicate execution is started.

## 7.5 Worker execution validation

Before ACK, `hiclaw task execute` validates:

```text
assigned_worker == AGENTTEAMS_WORKER_NAME
attempt >= 1
now <= deadline
all referenced input files stay inside allowlisted roots
all input digests match
active Skill name/version match the envelope
active observed generation is ready
idempotency key matches recomputation
```

The Worker then:

1. ACKs;
2. transitions to `RUNNING`;
3. invokes the Skill manifest command with `--input` and `--output` JSON files;
4. validates the result is JSON and conforms to the declared contract;
5. publishes the typed result and bounded summary;
6. transitions to the result state.

Duplicate identical results are accepted idempotently. Different result bytes for the same idempotency key force `CONFLICT`.

## 8. Argus Project DAG

## 8.1 Initial assessor phase

Argus registers and dispatches four required assessor Tasks in parallel:

- dependency;
- code;
- security;
- delivery.

Every Worker reads the same immutable source snapshot and validates its digest.

## 8.2 Meta phase

Meta starts only after all four required machine artifacts validate.

Validation covers:

- expected agent role;
- input snapshot ID;
- active Skill name/version;
- generation/digest observation;
- artifact schema;
- required status;
- upstream artifact references.

`result.md` is human-readable output and cannot unlock the DAG without a valid machine artifact.

## 8.3 Revision/recheck phase

When Meta returns `REVISION_NEEDED` with a `HALLUCINATION` reason:

1. Argus registers a real revision Task for the owning Worker;
2. the revision input contains public reason codes and original artifact references, not private reasoning;
3. Argus dispatches and waits for a real Worker result;
4. Argus registers and dispatches `meta-recheck-N`;
5. Synth dependency is replaced with the recheck Task;
6. Synth remains locked until recheck resolves the finding.

Maximum revisions per original Task: two. A third request moves the Project to `human-wait`.

## 8.4 Synth phase

Synth starts only when all required upstream artifacts and rechecks validate. A required failure, timeout, conflict, missing artifact, schema mismatch, or Skill identity mismatch cannot produce pass.

## 9. Read-Only Source Snapshot

For `current-source` mode, Argus inventories the target with read-only Git commands and never runs checkout, clean, add, reset, dependency installation, build, or target code.

The snapshot includes:

- tracked files;
- tracked modifications;
- untracked source files;
- deleted tracked paths as manifest records.

It excludes:

```text
.git/**
node_modules/**
**/__pycache__/**
**/.pytest_cache/**
**/*.pyc
dist/**
**/dist/**
build/**
**/build/**
coverage/**
**/coverage/**
diagnostic profiles
temporary test/video directories
*.png
*.mp4
```

Every exclusion records an exact reason. ZIP paths and timestamps are deterministic. `E:\heishou\koubo` is a read-only acceptance target.

## 10. Security and Leakage Boundary

A shared recursive sanitizer applies to:

- Matrix messages;
- Task errors and terminal summaries;
- Worker stdout/stderr excerpts;
- typed artifacts before external materialization;
- MinIO helper errors;
- local reports and traces;
- acceptance evidence.

Forbidden private fields include:

```text
private_reasoning
reasoning_text
raw_prompt
raw_response
source_code
secret
api_key
```

The random-canary E2E scans:

- Matrix history;
- MinIO outside the exact source-input fixture;
- Worker Task directories;
- all six Worker logs;
- Manager and Controller logs;
- local stdout/stderr;
- reports and traces;
- SQLite state.

Evidence stores counts, sanitized paths, and HMAC/digests, never raw matched secrets.

## 11. Failure and Rollback Semantics

### 11.1 Skill readiness failures

| Failure | Required behavior |
|---|---|
| Nacos version missing | Preserve current generation; mark Skill not ready |
| Unsafe archive or invalid structure | Reject before staging |
| Download/upload interruption | Do not update desired generation |
| Staged digest mismatch | Reject generation |
| Worker download/digest mismatch | Keep current active generation; observed `ready=false` |
| Partial activation failure | Roll back the full managed Argus Skill set |
| Removed remote Skill | Remove only the previously managed directory after successful activation |

Errors exposed outside Controller/Worker logs use bounded public error codes.

### 11.2 Task failures

| Failure | Required behavior |
|---|---|
| Matrix send failure | Task remains durably dispatched; allow one same-attempt retry |
| ACK timeout | Retry once, then `TIMED_OUT` |
| Runtime timeout after ACK | No concurrent duplicate; terminal timeout/human wait |
| Missing typed artifact | Required Task cannot complete successfully |
| Invalid schema or upstream reference | Required Task fails validation |
| Duplicate identical result | Idempotent success |
| Divergent duplicate result | `CONFLICT` |
| Required Task failure | Project becomes `human-wait`/unknown, never pass |

## 12. Test Strategy

## 12.1 AgentTeams tests

### Nacos and Skill convergence

- exact version query;
- missing version rejection;
- archive traversal, symlink, special-file, and malformed-layout rejection;
- canonical directory digest stability;
- complete generation staging and re-read verification;
- update overwrite plus stale-file removal;
- unmanaged Skill preservation;
- multi-Skill atomic activation;
- rollback on second-Skill failure;
- observed version/digest agreement;
- removal limited to previously managed remote Skills.

### Task/ACK

- immutable registration and request persistence;
- one-way transition table;
- stale revision conflict;
- structured full Matrix mention;
- dispatch persisted before Matrix send;
- one same-attempt retry;
- Worker ownership enforcement;
- assignment/deadline/input/version/idempotency validation before ACK;
- one Skill execution per idempotency key;
- identical and divergent duplicate result behavior;
- required typed artifact enforcement.

### Build identity

- `/api/v1/version` exposes upstream tag/SHA, fork SHA, patch digest, Skill distribution protocol version, Task protocol version, and kube mode;
- Controller, Manager, and Worker OCI labels agree;
- release evidence records immutable RepoDigests.

## 12.2 Argus tests

- all eight Skills execute in isolated copied directories without host-only imports;
- vulnerable/fixed golden fixtures for four assessors;
- `skills.lock.json` contains exactly eight unique explicit versions;
- Worker identities and `remoteSkills` assignments match the approved mapping;
- current-source snapshot inclusion, exclusion, deletion, and immutability;
- ProjectDriver ordering, resume, duplicate reconciliation, timeout, and failure behavior;
- real hallucination revision and Meta recheck;
- formal CLI engine selection;
- recursive sanitizer and distributed random-canary leakage tests;
- exact cleanup manifest;
- preliminary-document claims match measured evidence.

## 13. Phase-One Acceptance A1–A8

| Item | Requirement |
|---|---|
| A1 | Built-in Demo deterministic local audit produces valid evidence |
| A2 | Built-in Demo runs through real AgentTeams Workers and typed Tasks |
| A3 | Known gate/report paths remain deterministic and schema-valid |
| A4 | `E:\heishou\koubo` current-source snapshot runs through real Workers; any truthful gate is accepted |
| A5 | Six Workers, eight unique Nacos Skill versions, and all assigned Skills observed ready |
| A6 | Argus unit/contract/integration/security suites and AgentTeams unit/race/integration/regression suites pass separately |
| A7 | Random canary has zero raw occurrences outside the exact permitted source fixture |
| A8 | README, preliminary introduction, and PPT outline match measured Worker, Skill, engine, and closure facts |

Only 8/8 PASS produces:

```text
phase_one = accepted
```

Any FAIL or BLOCKED item means phase one is not accepted.

Before and after acceptance, Argus records and compares the `koubo` Git status. Argus must not change the target. Concurrent user changes are distinguished through snapshot manifests and timestamps; Argus never resets them.

## 14. Migration from the Interrupted Experimental Implementation

The AgentTeams checkout currently contains uncommitted experiments from the superseded package-v2 direction. Migration must be surgical.

### Retain and adapt

- generic Task types/store/handlers;
- Task CLI and one-shot Worker executor;
- Matrix structured mention support;
- Task authorization;
- typed-task-execution Worker instructions;
- buildinfo/version scaffolding;
- safe ZIP parsing helpers and canonical digest helpers that are useful to Nacos Skill validation;
- atomic activation logic after moving it under the `remoteSkills` generation contract.

### Remove or revert

- package upload response fields that introduce manifest v2 as the Skill control plane;
- `managed_artifacts` package manifest declarations and parsing;
- `DeployToMinIO` branching on package manifest v2;
- package-specific extracted managed-inventory code;
- the standalone `managed-artifacts-sync.py` name and contract;
- Worker entrypoint logic that runs a second independent Skill convergence system.

### Preserve untouched

`install/hiclaw-install.ps1` contains pre-existing unrelated local changes. Migration must not edit, stage, revert, or commit that file.

Argus historical untracked documentation and cache files must not be staged as part of this migration.

## 15. Implementation Sequence

1. cleanly separate retained Task/build changes from superseded package-v2 experiments;
2. add failing tests for explicit-version Nacos Skill convergence and atomic activation;
3. implement `remoteSkills` complete-generation staging and Worker observed state;
4. complete generic Task/ACK, one-shot execution, and build identity;
5. publish and lock eight self-contained Argus Skills in private Nacos;
6. implement source snapshot, Argus Task client, ProjectDriver, real revision/recheck, and formal AgentTeams CLI path;
7. implement sanitizer, leakage E2E, acceptance, cleanup, and measured docs;
8. build fixed images, capture RepoDigests, and run A1–A8 against `koubo`.

The prior decision to defer test execution until the unified gate remains in force for the interrupted implementation session. The revised implementation plan must still create the missing tests before production changes and must list every deferred verification command explicitly.
