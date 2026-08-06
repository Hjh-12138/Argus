# AgentTeams Live Acceptance Fixes (2026-08-06)

Full Argus Phase-One acceptance (A1–A8) now passes, including the two AgentTeams
live items that had been blocked for days. This document records the complete
fix chain discovered during live debugging so the non-obvious parts are not
lost.

Run: `20260806-132340-84053d` — `phase_one=accepted`.

## The blockers

The deterministic typed-task executor was already sound when invoked manually,
but live A2/A4 never completed on real Workers. Seven independent gaps stacked
up. In order encountered:

### 1. Room messages dropped at the mention gate (silent root cause)

The worker's generated `openclaw.json` had no `messages.groupChat.mentionPatterns`.
OpenClaw's matrix plugin drops every room message when `wasMentioned` is false,
and without any mention patterns `wasMentioned` is *always* false:

```
isRoom && requireMention && !wasMentioned  → skip "no-mention"
```

So Controller typed-task dispatches never reached `before_dispatch` (or the
model). This alone explains why A2/A4 "did not complete" even before the LLM
reliability question. Fix: the worker config generator
(`internal/agentconfig/generator.go` in the fork) must emit
`messages.groupChat.mentionPatterns: ["@" + workerName]`. The mention regex is
case-insensitive and unanchored, so `@argus-dep` matches
`ARGUS_TYPED_TASK ... @argus-dep:matrix-local...`.

### 2. The typed-task plugin's `before_dispatch` hook

`worker/extensions/argus-typed-task/` registers a high-priority `before_dispatch`
hook: after Matrix policy/session routing it claims anchored
`ARGUS_TYPED_TASK` messages, validates the task ID, and runs
`hiclaw task execute --id <id> -o json` via argv (`shell:false`, 30 min
timeout, bounded output). Recognized-but-invalid messages are claimed
(`handled:true`) so they never fall through to the model. This removes the LLM
from the execution-critical path. Bundled via `worker/Dockerfile`, enabled in
`worker-openclaw.json.tmpl` **and** in `generator.go` (the controller is what
actually generates worker configs in the embedded stack; the shell template
alone does nothing there).

### 3. Skills not materialized after worker recreation

After deleting/recreating the 6 worker containers, each worker's
`.skills/observed.json` claimed the role skills were `ready` while the actual
`skills/` directory was empty (stale state from the old container). The
executor then failed with `SKILL_MANIFEST_MISSING`. Fix: delete the stale
`.skills/observed.json` and run `python3 /opt/hiclaw/scripts/remote-skills-sync.py`
per worker to materialize the skills from the MinIO generation.

### 4. Worker hiclaw binary was stale

The `agentteams/worker-agent:argus.2` image carries a hiclaw binary whose
`syncTaskInputs` did not reliably fetch shared inputs, producing
`input digest mismatch` even when the MinIO object and envelope digest matched.
Fix: `docker cp` a freshly cross-compiled hiclaw
(`GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build ./cmd/hiclaw`) into each worker.

### 5. Executor did not publish the machine artifact to shared storage

The executor POSTed the result to the Controller (task=COMPLETED) but never
mirrored `result.json` to `shared/tasks/<id>/artifacts/result.json`, which is
where `ProjectDriver._artifact` reads it. Result: the driver found "missing
machine artifact" and returned `human-wait`. Fix: after running the skill, the
executor `mc cp`s the result to shared storage
(`publishResultArtifactToShared` in `cmd/hiclaw/task_cmd.go`).

### 6. Registry fixture not passed to the dependency assessor

`cli/argus.py:_audit_agentteams` called `driver.run(...)` without the registry,
so `assessor_payload` for `dep` omitted `payload["registry"]` and the dep skill
found zero findings (every manifest entry "unverified"). The vulnerable demo
then passed with 0 findings. Fix: load the registry fixture and pass it as
`registry=` to `driver.run`.

### 7. Assessor skills missing `context_lines` for critical/high findings

The local `agents/*/detector.py` detectors emit `evidence.context_lines`, so
`core/meta.py` verifies their findings. The agentteams skill copies
(`skills/argus-dependency-inspect`, `skills/argus-secret-scan`) did not, so the
`argus-evidence-verify` skill labeled every critical/high finding
`NEEDS_EVIDENCE` → no verified findings → gate pass. Fix: add `context_lines`
to the skills' evidence (matching the local detectors). The secret-scan skill
must redact the line (`_redact`) so the raw secret never appears in output —
the contract test enforces this.

### 8. Synth skill key mismatch

`synth_payload` provides `meta_decisions` and `agent_results`, but the
`argus-release-policy-evaluate` skill read `decisions` and `results` → empty
input → `verified:[]`, `blocking:[]`, gate pass even with verified findings.
Fix: read `payload.get("meta_decisions") or payload.get("decisions")` (same for
agent_results/results).

## Deployment flow that worked

1. Rebuild controller: `build-hiclaw-controller` + `build-embedded` (Makefile
   copies `manager/agent` into the controller build context; `make` is
   unavailable on Windows so run the `docker build` commands directly).
2. Recreate `agentteams-controller` from the new embedded image preserving
   env/mounts/network/restart. Reconstruct the `docker run` from a backup
   container via `docker inspect`. **Must set `MSYS_NO_PATHCONV=1`** when
   running the `docker run` or the `-e PATH=/opt/...` value gets MSYS-mangled
   and supervisord is "not found".
3. Delete the 6 worker containers, then `hiclaw worker wake --name argus-<role>`
   to force controller recreation (fresh token + regenerated config).
4. `docker cp` the plugin files + clean hiclaw binary into the recreated
   (crashed) workers; `docker start` them.
5. Delete `.skills/observed.json` + run `remote-skills-sync.py` per worker.
6. `docker cp` any updated Argus skill `main.py` into the worker skill dirs.

## Regression coverage

- Fork: `internal/agentconfig/generator_test.go` asserts the plugin entry and
  the mention pattern. `internal/backend/docker_test.go` covers the token
  rotation (create/seed/refresh/stopped). `docker_live_test.go` is a gated
  (`AGENTTEAMS_DOCKER_LIVE_TEST=1`) live-daemon test.
- Argus: `tests/contract/test_assessor_skill_contracts.py` (context_lines +
  secret redaction), `tests/unit/test_agentteams_cli_state.py` (registry via
  `getattr`), `tests/unit/test_agentteams_skill_lock.py` (lock digests match).
