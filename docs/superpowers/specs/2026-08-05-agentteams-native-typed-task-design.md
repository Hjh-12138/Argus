# AgentTeams-Native Typed Task Execution Design

## Context

Argus phase-one acceptance A2 and A4 time out with typed tasks left in `DISPATCHED`. The current `ProjectDriver` registers Controller-owned tasks with an empty `room_id`, so `TaskHandler.Dispatch` persists the transition but does not send the structured Matrix wake-up. This bypasses AgentTeams v1.2.0-beta.1's intended execution architecture: Project Room communication, full Matrix `m.mentions`, OpenClaw current-message routing, the `typed-task-execution` Skill, and `hiclaw task execute`.

The same path declares `shared/projects/<project-id>/snapshot.zip` as a hashed input but publishes only `snapshot.id`. Even after restoring the wake-up, Worker preflight would reject the missing archive before ACK.

The intended outcome is a truthful end-to-end path in which real Workers receive visible, actionable Matrix signals, execute the existing typed-task protocol exactly once, publish machine artifacts, and allow A2/A4 to reach terminal results without introducing an out-of-band queue poller.

## Architecture

Argus remains the DAG coordinator. AgentTeams remains the collaboration and execution runtime.

```text
Argus ProjectDriver
  -> create AgentTeams Project + Project Room
  -> publish snapshot.zip and metadata
  -> register typed task with real room_id
  -> Controller persists REGISTERED -> DISPATCHED
  -> Controller sends ARGUS_TYPED_TASK + structured m.mentions
  -> OpenClaw Worker wakes on its full Matrix ID
  -> Worker routes Current message to typed-task-execution
  -> hiclaw task execute validates, ACKs, starts, executes, and publishes result
  -> Argus waits on Controller task state and reads machine artifact
```

Matrix is the executable-signal and human-visible audit surface. Controller task state and artifacts remain the machine source of truth. No task-list API, MinIO task scanner, or Worker queue poller is added.

## Components and Responsibilities

### `agentteams/project_driver.py`

`ProjectDriver.run()` must create one AgentTeams Project before registering tasks. It will:

1. Derive a title and the six participating Worker names.
2. Call the existing `HiclawClient.create_project()` implementation.
3. Require a non-empty `project_room_id`; failure stops the audit before task registration.
4. Publish project metadata containing the room, run ID, snapshot identity, participating Workers, and task IDs.
5. Pass the room ID to every assessor, Meta, revision, Synth, and report task.

`_register_task()` will accept `room_id` and write it into the envelope instead of using an empty string.

This reuses the proven project setup pattern in `agentteams/orchestrator.py` rather than duplicating Matrix room creation.

### `agentteams/hiclaw_client.py`

Add a binary-safe shared-file publication method. It must:

- validate the shared-relative destination;
- stream exact bytes into the Manager container without text decoding;
- upload from a private temporary file to MinIO first;
- update the Manager shared mirror only after remote publication succeeds;
- clean up temporary files on every path.

The existing `publish_shared_text()` remains for JSON and Markdown.

### Snapshot publication

Before creating the first typed task, `ProjectDriver` publishes:

- `shared/projects/<project-id>/snapshot.zip`: the exact local archive bytes;
- `shared/projects/<project-id>/snapshot.id`: JSON metadata with snapshot ID and archive SHA-256.

The published archive's SHA-256 must match `SnapshotReference.archive_sha256`. A missing archive, upload failure, or digest mismatch stops the audit before registration.

### Existing AgentTeams runtime

The following fork behavior remains the primary implementation and should not be replaced:

- `TaskHandler.Dispatch` sends `ARGUS_TYPED_TASK` only for a non-empty task room.
- `SendMessageWithMentions` includes the assigned Worker's full Matrix ID in `m.mentions.user_ids`.
- OpenClaw wakes only on a valid full mention.
- Worker `AGENTS.md` gives Controller-owned typed tasks precedence over ordinary project workflow.
- `typed-task-execution` extracts a validated task ID and runs `hiclaw task execute`.
- `executeTaskWithClient` owns assignment, input, idempotency, Skill observation, ACK, START, execution, and result validation.

## Data Flow

1. `ProjectDriver` ensures the required Worker set is available through the existing caller setup.
2. It creates the AgentTeams Project and obtains `project_room_id`.
3. It publishes the snapshot archive and metadata.
4. It registers an assessor task containing:
   - the real Project Room ID;
   - the assigned Worker;
   - observed Skill generation and digest;
   - the published snapshot path and digest;
   - the computed idempotency key.
5. It dispatches the task.
6. Controller persists `DISPATCHED`, then sends the bounded Matrix wake-up with a structured mention.
7. OpenClaw receives the message as the current message and loads `typed-task-execution`.
8. `hiclaw task execute` retrieves the Controller envelope rather than trusting chat content.
9. The executor validates all preconditions, ACKs, starts, runs the declared Skill command, and publishes a terminal result.
10. Argus polls Controller state and reads the task artifact from shared storage.
11. The same sequence advances through Meta, optional revision, Synth, and report tasks.

## Error Handling

- **Project creation failure or missing room:** stop before registration and surface a system error.
- **Snapshot archive missing or digest mismatch:** stop before registration; do not dispatch an unverifiable task.
- **Task registration failure:** stop the DAG and preserve the public Controller error.
- **Matrix wake-up failure:** Controller returns 502 after persisting `DISPATCHED`; Argus reports a truthful partial/system error and does not claim completion.
- **Worker timeout:** include task ID and last observed state in the error. No silent success.
- **Skill/input/identity/result failure:** preserve the existing fail-closed typed-task behavior and bounded public codes.
- **Duplicate wake-up:** the existing local task result guard and Controller revision checks must prevent a second Skill execution.
- **HTTP 401:** verify on the restored real path with a newly created Worker. Treat Docker token rotation as a separate confirmed bug only if live evidence shows immediate missing-token failure or age-correlated expiry. Never distribute Controller admin credentials to Workers.

## Tests

### Argus unit tests

Add focused tests proving:

1. `ProjectDriver` creates a Project before task registration.
2. A missing `project_room_id` fails before any task is registered.
3. Every typed-task envelope carries the created Project Room ID.
4. `snapshot.zip` is published before task registration and dispatch.
5. Published bytes and declared SHA-256 match exactly.
6. Binary publication does not pass archive bytes through UTF-8 text conversion.
7. Matrix dispatch errors and terminal timeouts cannot produce `status=completed`.

### AgentTeams tests

Keep the existing handler tests for bounded structured mentions and payload non-leakage. Harden `tests/test-task-worker-execution.sh` so it:

1. Creates a real Worker and Project Room.
2. Deploys the deterministic Skill and waits for observed readiness.
3. Registers a protocol-valid task with the real room ID and exact idempotency key.
4. Dispatches and waits for ACK, RUNNING, and COMPLETED.
5. Verifies the result artifact and execution counter.
6. Sends an identical duplicate executable signal and proves the counter stays at one.
7. Returns nonzero for failed assertions; prerequisite skips are allowed only before the live scenario starts.
8. Preserves all cleanup traps instead of overwriting the Worker cleanup handler.

### End-to-end verification

1. Run focused Argus unit tests.
2. Run AgentTeams Go task/store/server tests.
3. Run the hardened real Worker execution test.
4. Recreate the six Argus Workers to avoid stale runtime state.
5. Run the A2 vulnerable demo audit and require exit 2 plus `status=completed`.
6. Run the A4 Koubo current-source audit and require a truthful terminal state plus `status=completed`.
7. Run local and live pytest suites.
8. Run full A1-A8 acceptance and inspect generated JSON evidence.

## Scope Boundaries

Included:

- AgentTeams Project Room creation in typed `ProjectDriver`;
- real Matrix executable signals via existing Controller dispatch;
- binary snapshot publication;
- focused correctness tests and truthful live verification;
- minimal AgentTeams test hardening needed to prove the runtime path.

Excluded unless separately proven by live evidence:

- Controller task-list APIs or Worker polling loops;
- direct Controller-to-Worker execution endpoints;
- MinIO task queue scanning;
- automatic replay of tasks that crash after entering `RUNNING`;
- broad support changes for CoPaw, Hermes, or OpenHuman;
- Docker ServiceAccount token rotation refactoring without a reproduced 401 on the restored path;
- unrelated cleanup or modification of `install/hiclaw-install.ps1`.

## Success Criteria

The implementation is complete when:

- every Argus typed task belongs to a real AgentTeams Project Room;
- Controller dispatch emits a structured full-ID Matrix mention;
- a real OpenClaw Worker receives the signal and runs `hiclaw task execute`;
- the declared snapshot archive exists and passes digest validation;
- the deterministic fixture executes exactly once under duplicate wake-up;
- A2 and A4 reach truthful terminal results rather than timing out in `DISPATCHED`;
- no queue poller or elevated shared controller credential is introduced;
- Koubo remains read-only throughout acceptance.
