# AgentTeams Worker Model Configuration Repair Design

Date: 2026-08-10
Status: Approved for implementation planning

## Problem

The live A1-A8 acceptance run fails when Argus Workers invoke the AgentTeams AI Gateway. OpenClaw surfaces the generic error:

```text
LLM request failed: provider rejected the request schema or tool payload.
```

The Provider's raw HTTP 400 response identifies the direct cause:

```text
The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed model.
```

All six Argus Workers resolve their effective model to the literal placeholder `model`, while the Manager correctly uses `deepseek-v4-flash`. Matrix room exports show repeated retries but no successful Worker inference. The Manager later inferred a tool-schema/image incompatibility, but runtime logs still reported `model=model`; therefore that later inference is unsupported until model configuration is corrected and tool use is tested independently.

## Goals

1. Make `agentteams/contract.lock.json` the single authoritative Worker model source.
2. Prevent placeholders or unsupported model names from entering Worker resources.
3. Verify the effective model after applying Worker configuration.
4. Separate model-connectivity verification from tool-schema compatibility verification.
5. Fail A1-A8 quickly when live Worker configuration is invalid.
6. Reconfigure the six Argus Workers and rerun the complete live A1-A8 acceptance suite.
7. Preserve current source changes, MinIO history, and project-room history.

## Non-goals

- Adding a Gateway fallback that silently rewrites invalid models.
- Refactoring unrelated AgentTeams orchestration behavior.
- Deleting historical `.argus` or MinIO artifacts.
- Treating a Worker phase of `Running` as proof that LLM inference works.
- Declaring the Worker image or tool schema incompatible before an independent tool-enabled smoke test fails with a valid model.

## Architecture

The configuration flow is:

```text
agentteams/contract.lock.json
        |
        v
load_locked_model()
  - require a non-empty string
  - reject placeholders
  - require an explicitly supported Gateway model
        |
        v
apply_worker_configuration()
  - preserve Worker runtime, image, soul, and remoteSkills
  - write the validated model into every Worker resource
        |
        v
Controller rollout / Worker recreation
        |
        v
verify_effective_model()
  - verify control-plane model
  - verify all six Workers become healthy
  - verify runtime inference uses the locked model
        |
        v
model-only smoke gate
        |
        v
argus-code tool-enabled smoke gate
        |
        v
A1-A8 live acceptance
```

### Configuration authority

`agentteams/contract.lock.json` remains the only source of the expected model. No second model configuration file is introduced. Environment configuration may supply Gateway credentials and endpoints but must not silently override the locked Worker model during provisioning.

### Model validation

A shared validator accepts the locked model only when all conditions hold:

- it is a string;
- it is non-empty after trimming;
- it is not a known placeholder such as `model`, `default`, `placeholder`, `test`, or `unknown`;
- it is in the explicitly supported AgentTeams Gateway model set.

The initial supported set is:

```text
deepseek-v4-flash
deepseek-v4-pro
```

Validation occurs at the provisioning boundary before a Worker CR is generated or applied. The low-level Worker-apply method also validates its model argument so alternate callers cannot bypass the guard.

### Provisioning entry point

A focused provisioning entry point reads the model lock and skill lock, applies all six Worker definitions, waits for convergence, and reports sanitized diagnostics. It replaces ad hoc commands and historical scripts as the documented way to synchronize live Argus Workers.

The entry point must:

1. validate all local inputs before changing any Worker;
2. capture a sanitized pre-change Worker snapshot;
3. preserve each Worker's declared runtime, image, soul, and remoteSkills;
4. apply the same locked model to all six Workers;
5. wait for control-plane and container convergence;
6. verify remote Skill observations still match `skills/skills.lock.json`;
7. verify the effective model before returning success.

The snapshot records names, phases, images, runtimes, models, and skill names. It excludes API keys, Matrix tokens, passwords, and other credentials.

## Verification gates

### Control-plane gate

For every Argus Worker:

- the Worker resource exists;
- phase is healthy (`Ready` or `Running`, according to the pinned AgentTeams contract);
- effective model equals `agentteams/contract.lock.json:model`;
- runtime and image remain the expected pinned values;
- observed ready Skills exactly match the lock assignment.

Any mismatch stops the process before A1-A8.

### Model-only LLM smoke gate

Each Worker receives a fixed, short request that does not require tool use. Success proves:

- the Worker receives Matrix/task input;
- OpenClaw constructs an LLM request;
- the request reaches the Provider;
- the Provider accepts the model;
- the Worker returns a normal response.

The smoke evidence must confirm `deepseek-v4-flash` as the effective model and must contain no `model=model` or Provider 400 event.

### Tool-enabled smoke gate

After the model-only gate passes, `argus-code` receives a minimal task that exposes its actual tools and invokes `argus-code-rule-scan`. This independently tests the hypothesis that the Worker tool schema may be incompatible with the Gateway.

If this gate fails with a valid model, the failure is investigated as a separate tool-schema issue using the raw Provider reason. It is not conflated with model provisioning.

## Error handling and rollback

The provisioning operation follows validate-before-mutate and fail-fast behavior:

1. Validate lock files and all six Worker definitions.
2. Capture sanitized current state.
3. Apply Worker resources.
4. Wait for convergence.
5. Stop at the first unresolved mismatch and report all evidence already collected.

Diagnostics include:

```text
worker=<name>
expected_model=<locked model>
effective_model=<observed model>
phase=<phase>
provider_status=<status when available>
provider_reason=<sanitized raw reason when available>
```

Generic wrapper errors must not replace the raw Provider reason. Sensitive fields are redacted.

The operation does not automatically delete project data or MinIO history. If rollout fails, the sanitized pre-change snapshot is retained for operator-directed restoration. The implementation may reapply a known-good Worker configuration within the authorized scope, but it must not guess missing credentials or silently downgrade models/images.

## Acceptance integration

The live acceptance runner gains a preflight before A1:

- validate the locked model;
- verify all six Worker effective models;
- verify Worker health and Skill assignments;
- run or require the smoke gates.

If preflight fails, A1-A4 and live A6 are not dispatched. The acceptance result reports a concrete configuration failure instead of spending multiple 30-minute task windows producing duplicate Provider errors.

The complete acceptance run uses both live flags:

```text
--agentteams-live
--leakage-e2e
```

Success criteria are:

- **A1:** vulnerable demo blocks with dependency, security, and delivery categories;
- **A2:** vulnerable demo completes on real Workers and blocks;
- **A3:** fixed demo completes with gate `pass` and no vulnerable categories;
- **A4:** the requested current-source target completes on real Workers;
- **A5:** eight locked Skills, six assignments, and six valid Worker models converge;
- **A6:** local and live AgentTeams test suites pass;
- **A7:** the random canary is absent from reports, audit output, evidence, and MinIO reports;
- **A8:** README, introduction, PPT outline, and generated `acceptance.md` match the measured run.

The final report must cite the newly generated run ID and must not reuse historical PASS results.

## Test design

Implementation follows test-driven development.

### Unit tests

- reject empty models;
- reject `model` and other placeholders;
- reject unsupported model names;
- accept `deepseek-v4-flash` and `deepseek-v4-pro`;
- verify a valid model is serialized into the Worker CR;
- verify low-level apply rejects invalid models even if called directly;
- verify sensitive data is absent from state snapshots and errors.

Existing tests that pass the literal `model` as a generic argument are changed to use a valid explicit test model. Placeholder rejection is tested separately.

### Provisioning tests

- all six Workers use the lock model;
- a control-plane model mismatch fails convergence;
- Skill assignment mismatches still fail convergence;
- an invalid lock fails before any apply call;
- partial rollout reports the affected Worker and does not start acceptance.

### Acceptance tests

- model preflight failure prevents A1-A4/live-A6 dispatch;
- successful preflight allows the existing A1-A8 sequence;
- raw Provider model errors are safely preserved;
- live A1-A8 produces a new acceptance run with all eight items passing.

## Deployment sequence

1. Add failing unit and preflight tests.
2. Implement shared model loading and validation.
3. Add effective-model observation and sanitized snapshots.
4. Add the focused six-Worker provisioning command.
5. Add the A1-A8 live preflight.
6. Run local targeted tests, then the complete non-AgentTeams suite.
7. Capture the current six-Worker state.
8. Apply the locked model to all six Workers and permit Controller rollout/recreation.
9. Verify phase, image, runtime, model, and Skills for every Worker.
10. Run model-only smoke checks for all six Workers.
11. Run the `argus-code` tool-enabled smoke check.
12. Run A1-A8 with live AgentTeams and leakage checks.
13. Report the new run ID, item statuses, test counts, and any remaining failures without claiming success if any gate fails.

## Safety and workspace constraints

The repository currently contains substantial uncommitted work, including orchestration migration changes and generated acceptance artifacts. Implementation must modify only files required for this repair and must not reset, clean, or overwrite unrelated changes. Generated runtime evidence is reported separately from source changes.
