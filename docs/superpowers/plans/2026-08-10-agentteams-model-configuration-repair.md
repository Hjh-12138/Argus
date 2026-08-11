# AgentTeams Worker Model Configuration Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `agentteams/contract.lock.json` the validated single source of Worker model configuration, apply `deepseek-v4-flash` to all six Argus Workers with effective-state verification, and rerun the complete live A1-A8 acceptance suite.

**Architecture:** Add a focused model-policy module that validates the locked model and produces sanitized diagnostics. Extend the existing `HiclawClient` boundary so invalid models cannot be applied and add a dedicated six-Worker synchronizer that applies the lock model, waits for Worker/Skill convergence, and verifies the effective model before acceptance. Add an acceptance preflight so invalid live configuration stops A1-A4/live A6 before dispatch; after the preflight passes, run a model-only smoke gate, an `argus-code` tool-enabled smoke gate, and the existing A1-A8 runner.

**Tech Stack:** Python 3.13, pytest, Docker/AgentTeams v1.2.0-beta.1, Matrix Project Rooms, MinIO, Nacos remote Skills, DeepSeek OpenAI-compatible Gateway.

## Global Constraints

- `agentteams/contract.lock.json` is the only authoritative Worker model source.
- The accepted Gateway models are exactly `deepseek-v4-flash` and `deepseek-v4-pro`.
- Reject the literal placeholders `model`, `default`, `placeholder`, `test`, and `unknown` before any Worker apply.
- Do not add a Gateway fallback that silently rewrites invalid model names.
- Do not reset, clean, or overwrite unrelated uncommitted changes in the working tree.
- Do not delete historical `.argus` or MinIO artifacts.
- Do not place API keys, Matrix tokens, passwords, or raw credentials in snapshots, logs, or acceptance evidence.
- A Worker phase of `Running` is not sufficient evidence that LLM inference works.
- Do not claim A1-A8 success unless the newly generated acceptance run reports all eight items as `PASS`.

---

## File Map

### New files

- `agentteams/model_config.py` — pure model-policy functions: supported models, lock loading, validation, and sanitized model mismatch formatting.
- `agentteams/apply_worker_config.py` — live six-Worker synchronizer and command entry point; applies the validated lock model, waits for convergence, and emits sanitized JSON diagnostics.
- `tests/unit/test_model_config.py` — pure validator and lock-loading tests.
- `tests/unit/test_agentteams_worker_config.py` — provisioning/client boundary tests with fake clients and captured Worker YAML.

### Modified files

- `agentteams/hiclaw_client.py` — reject invalid model arguments in Worker apply methods; expose a safe effective-model read/normalization helper without exposing credentials.
- `agentteams/worker_payloads.py` — define pinned model/runtime/image constants used by the synchronizer and keep Worker definitions aligned with `skills.lock.json`.
- `tests/unit/test_agentteams_skill_lock.py` — replace generic `model` arguments in existing tests with `deepseek-v4-flash`, and add direct invalid-model regression coverage.
- `acceptance/phase_one.py` — add live Worker model/health/Skill preflight before A1-A4 and live A6; report concrete mismatches.
- `tests/unit/test_acceptance_runner.py` — cover preflight pass/fail behavior and ensure no live audit command starts after a failed preflight.
- `docs/superpowers/specs/2026-08-10-agentteams-model-configuration-design.md` — already approved design source of truth; implementation must follow it.

---

## Task 1: Establish the failing model-policy tests

**Files:**
- Create: `tests/unit/test_model_config.py`
- Modify: `tests/unit/test_agentteams_skill_lock.py`

**Interfaces:**
- The tests define the required public API in `agentteams.model_config`: `SUPPORTED_MODELS`, `PLACEHOLDER_MODELS`, `validate_model(model: str) -> str`, `load_locked_model(lock_path: Path) -> str`, and `model_mismatch(worker: str, expected: str, actual: object) -> str`.
- Later tasks implement these exact names and types.

- [ ] **Step 1: Add failing pure validation tests**

```python
from pathlib import Path

import pytest

from agentteams.model_config import (
    PLACEHOLDER_MODELS,
    SUPPORTED_MODELS,
    load_locked_model,
    model_mismatch,
    validate_model,
)


def test_supported_models_are_explicit():
    assert SUPPORTED_MODELS == frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})


@pytest.mark.parametrize("value", sorted(PLACEHOLDER_MODELS | {"", "   ", "gpt-unknown"}))
def test_invalid_models_are_rejected(value):
    with pytest.raises(ValueError):
        validate_model(value)


@pytest.mark.parametrize("value", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_supported_model_is_normalized(value):
    assert validate_model(f"  {value} ") == value


def test_lock_loader_requires_valid_model(tmp_path: Path):
    lock = tmp_path / "contract.lock.json"
    lock.write_text('{"model":"model"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_locked_model(lock)


def test_model_mismatch_is_sanitized():
    text = model_mismatch("argus-code", "deepseek-v4-flash", "model")
    assert text == (
        "worker=argus-code expected_model=deepseek-v4-flash "
        "effective_model=model"
    )
    assert "token" not in text.lower()
    assert "password" not in text.lower()
```

- [ ] **Step 2: Change existing test fixtures that use a generic model string**

In `tests/unit/test_agentteams_skill_lock.py`, change the existing calls that only need a valid model argument from `"model"` to `"deepseek-v4-flash"`. Keep the new invalid-model tests separate so the old tests no longer bless the production-failing placeholder.

- [ ] **Step 3: Run the new tests and confirm the expected collection failure**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_model_config.py tests/unit/test_agentteams_skill_lock.py -q
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'agentteams.model_config'`.

- [ ] **Step 4: Commit the failing-test checkpoint**

```powershell
git add tests/unit/test_model_config.py tests/unit/test_agentteams_skill_lock.py
git commit -m "test: define Worker model configuration policy"
```

---

## Task 2: Implement the pure model policy

**Files:**
- Create: `agentteams/model_config.py`
- Test: `tests/unit/test_model_config.py`

**Interfaces:**
- `SUPPORTED_MODELS: frozenset[str] = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})`.
- `PLACEHOLDER_MODELS: frozenset[str] = frozenset({"", "model", "default", "placeholder", "test", "unknown"})`.
- `validate_model(model: str) -> str` returns a trimmed supported model or raises `ValueError` with the invalid value but no credentials.
- `load_locked_model(lock_path: Path) -> str` loads a JSON object, requires a string `model`, and delegates to `validate_model`.
- `model_mismatch(worker: str, expected: str, actual: object) -> str` returns only `worker`, `expected_model`, and `effective_model` fields.

- [ ] **Step 1: Implement validation without external dependencies**

```python
from __future__ import annotations

import json
from pathlib import Path

SUPPORTED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
PLACEHOLDER_MODELS = frozenset(
    {"", "model", "default", "placeholder", "test", "unknown"}
)


def validate_model(model: str) -> str:
    if not isinstance(model, str):
        raise ValueError("Worker model must be a string")
    normalized = model.strip()
    if normalized.lower() in PLACEHOLDER_MODELS:
        raise ValueError(f"invalid Worker model placeholder: {normalized!r}")
    if normalized not in SUPPORTED_MODELS:
        raise ValueError(f"unsupported Worker model: {normalized!r}")
    return normalized


def load_locked_model(lock_path: Path) -> str:
    data = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("contract lock must be a JSON object")
    return validate_model(data.get("model"))


def model_mismatch(worker: str, expected: str, actual: object) -> str:
    return (
        f"worker={worker} expected_model={expected} "
        f"effective_model={actual}"
    )
```

- [ ] **Step 2: Run the focused tests**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_model_config.py tests/unit/test_agentteams_skill_lock.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit the policy implementation**

```powershell
git add agentteams/model_config.py tests/unit/test_model_config.py tests/unit/test_agentteams_skill_lock.py
git commit -m "feat: validate locked Worker models"
```

---

## Task 3: Enforce validation at the Worker apply boundary

**Files:**
- Modify: `agentteams/hiclaw_client.py:339-385`
- Create: `tests/unit/test_agentteams_worker_config.py`

**Interfaces:**
- `HiclawClient.apply_worker_remote_skills(name: str, model: str, runtime: str, soul: str, source: str, auth_type: str, skill_versions: dict[str, str]) -> None` remains backward-compatible but validates `model` before creating the temporary YAML.
- Add `HiclawClient.get_worker_effective_model(name: str) -> str | None`, using the existing `get_workers(name)` JSON response and checking the model fields exposed by the pinned CLI (`model`, `effectiveModel`, or `spec.model`) without reading credentials or arbitrary container files.
- Add `HiclawClient.worker_configuration(name: str) -> dict`, returning only sanitized fields needed by preflight: `name`, `phase`, `model`, `runtime`, `image`, and ready Skill names.

- [ ] **Step 1: Write failing boundary tests**

```python
from agentteams.hiclaw_client import HiclawClient


def test_apply_rejects_placeholder_before_writing_yaml():
    client = HiclawClient.__new__(HiclawClient)
    client.container = "unused"
    client._docker_exec = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("invalid model must fail before docker exec")
    )
    client._run = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("invalid model must fail before hiclaw")
    )

    try:
        client.apply_worker_remote_skills(
            "argus-code", "model", "openclaw", "", "nacos://nacos:8848/public",
            "nacos", {"argus-code-rule-scan": "0.0.6"},
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_effective_model_reads_sanitized_worker_state():
    client = HiclawClient.__new__(HiclawClient)
    client.get_workers = lambda name: [{
        "name": name, "phase": "Running", "model": "deepseek-v4-flash",
        "runtime": "openclaw", "image": "agentteams/worker-agent:test",
    }]
    assert client.get_worker_effective_model("argus-code") == "deepseek-v4-flash"
```

- [ ] **Step 2: Run the boundary tests and confirm they fail**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_agentteams_worker_config.py -q
```

Expected: FAIL because the apply boundary and effective-model accessor are not implemented.

- [ ] **Step 3: Add validation before temporary YAML creation**

At the first line of `apply_worker_remote_skills`, call `validate_model(model)`. Do not coerce invalid values to `deepseek-v4-flash`; reject them. Keep the existing `skills: []`, image, remoteSkills, runtime, and soul serialization unchanged.

- [ ] **Step 4: Add sanitized effective-state extraction**

Implement `get_worker_effective_model` by reading the already available `get_workers(name)` response. Prefer `model`, then `effectiveModel`, then nested `spec.model`; return `None` when no model field is present. Do not call `cat`, dump OpenClaw config, or print environment variables.

Implement `worker_configuration` using the same response plus `get_worker_skill_observation`, retaining only names and ready statuses. Never include container environment, command lines containing tokens, or raw API responses.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_agentteams_worker_config.py tests/unit/test_agentteams_skill_lock.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the apply-boundary change**

```powershell
git add agentteams/hiclaw_client.py tests/unit/test_agentteams_worker_config.py tests/unit/test_agentteams_skill_lock.py
git commit -m "feat: reject invalid Worker model configuration"
```

---

## Task 4: Add the six-Worker synchronizer

**Files:**
- Create: `agentteams/apply_worker_config.py`
- Modify: `agentteams/worker_payloads.py`
- Test: `tests/unit/test_agentteams_worker_config.py`

**Interfaces:**
- `SyncResult` is a dataclass with `model: str`, `workers: list[dict]`, and `errors: list[str]`.
- `sync_workers(client: HiclawClient, workspace: Path, timeout_s: int = 300) -> SyncResult` validates the lock, applies all six Worker configurations, waits for phase/Skill convergence, and raises `HiclawError` with sanitized mismatch details on effective-model mismatch.
- `capture_worker_snapshot(client: HiclawClient, workspace: Path) -> Path` writes a sanitized JSON snapshot beneath `.argus/model-config/` and returns its path.
- `main(argv: list[str] | None = None) -> int` supports `--workspace`, `--timeout`, and `--snapshot-only`, prints sanitized JSON, and returns `0` only when the requested snapshot or six-Worker synchronization succeeds.
- `worker_payloads.py` exports `WORKER_MODEL = "deepseek-v4-flash"`, `WORKER_RUNTIME = "openclaw"`, and `WORKER_IMAGE = "agentteams/worker-agent:v1.2.0-beta.1-argus.7"` as defaults used only after the lock model has been validated.

- [ ] **Step 1: Add failing synchronizer tests with a fake client**

```python
import json
from pathlib import Path

import pytest

from agentteams.apply_worker_config import sync_workers
from agentteams.hiclaw_client import HiclawError
from agentteams.worker_payloads import CORE_AGENTS, WORKERS


class FakeWorkerClient:
    def __init__(self, model="deepseek-v4-flash"):
        self.model = model
        self.applied = []

    def apply_worker_remote_skills(self, name, model, runtime, soul,
                                   source, auth_type, skill_versions):
        self.applied.append((name, model, runtime, skill_versions))

    def wait_ready(self, name, timeout_s):
        return True

    def get_worker_effective_model(self, name):
        return self.model

    def get_worker_skill_observation(self, name):
        worker = next(w for w in WORKERS.values() if w.name == name)
        return {"skills": [{"name": s, "ready": True} for s in worker.skills]}

    def get_workers(self, name=None):
        names = [WORKERS[a].name for a in CORE_AGENTS] if name is None else [name]
        return [{"name": n, "phase": "Running", "model": self.model}
                for n in names]


def test_sync_applies_lock_model_to_all_workers(tmp_path: Path):
    lock = {
        "source": "nacos://nacos:8848/public", "auth_type": "nacos",
        "skills": [{"name": s, "version": "0.0.6"}
                   for s in {skill for w in WORKERS.values() for skill in w.skills}],
    }
    lock["skills"] = sorted(lock["skills"], key=lambda x: x["name"])
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills/skills.lock.json").write_text(
        json.dumps(lock), encoding="utf-8")
    (tmp_path / "agentteams").mkdir()
    (tmp_path / "agentteams/contract.lock.json").write_text(
        '{"model":"deepseek-v4-flash"}', encoding="utf-8")

    client = FakeWorkerClient()
    result = sync_workers(client, tmp_path, timeout_s=1)
    assert result.model == "deepseek-v4-flash"
    assert {row[0] for row in client.applied} == {w.name for w in WORKERS.values()}
    assert {row[1] for row in client.applied} == {"deepseek-v4-flash"}


def write_locks(tmp_path: Path):
    skills = {skill for worker in WORKERS.values() for skill in worker.skills}
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "skills/skills.lock.json").write_text(json.dumps({
        "source": "nacos://nacos:8848/public",
        "auth_type": "nacos",
        "skills": [{"name": name, "version": "0.0.6"}
                   for name in sorted(skills)],
    }), encoding="utf-8")
    (tmp_path / "agentteams").mkdir(exist_ok=True)
    (tmp_path / "agentteams/contract.lock.json").write_text(
        '{"model":"deepseek-v4-flash"}', encoding="utf-8")


def test_sync_fails_when_effective_model_is_wrong(tmp_path: Path):
    write_locks(tmp_path)
    with pytest.raises(HiclawError, match="effective_model=model"):
        sync_workers(FakeWorkerClient("model"), tmp_path, timeout_s=1)
```

- [ ] **Step 2: Run synchronizer tests and confirm they fail**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_agentteams_worker_config.py -q
```

Expected: FAIL during import because `agentteams.apply_worker_config` does not exist.

- [ ] **Step 3: Implement lock/skill loading and deterministic apply order**

Load `agentteams/contract.lock.json` with `load_locked_model`. Load `skills/skills.lock.json`, build the source/auth/version map, and iterate `WORKERS.values()` in declaration order. For each Worker call `apply_worker_remote_skills` with the validated model and only that Worker's assigned Skill versions.

- [ ] **Step 4: Implement convergence and mismatch reporting**

For each Worker, wait until `wait_ready` succeeds, poll `get_worker_effective_model`, and compare it to the lock model. Poll `get_worker_skill_observation` and require exactly the assigned ready Skill set. A mismatch must include the sanitized `model_mismatch` text and must not include credentials.

- [ ] **Step 5: Implement sanitized snapshots and the command entry point**

Implement `capture_worker_snapshot(client, workspace)` by calling `worker_configuration` for the six names in `WORKERS`, writing only `name`, `phase`, `model`, `runtime`, `image`, and ready Skill names to `.argus/model-config/<UTC timestamp>/workers-before.json`, and returning the path.

Use `argparse`; default `--workspace` to the current directory and `--timeout` to `300`, and add `--snapshot-only`. With `--snapshot-only`, capture the sanitized state and exit without applying a Worker resource. Otherwise capture the snapshot before calling `sync_workers`. Catch `ValueError`, `HiclawError`, `OSError`, and `json.JSONDecodeError`; print a one-line sanitized error to stderr and return `4`. Print the successful model, snapshot path, and six Worker names as JSON without raw command output.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_agentteams_worker_config.py tests/unit/test_model_config.py -q
```

Expected: PASS.

```powershell
git add agentteams/apply_worker_config.py agentteams/worker_payloads.py tests/unit/test_agentteams_worker_config.py
git commit -m "feat: synchronize locked model across Argus Workers"
```

---

## Task 5: Add live acceptance preflight

**Files:**
- Modify: `acceptance/phase_one.py:124-156`
- Modify: `tests/unit/test_acceptance_runner.py`

**Interfaces:**
- Add `_agentteams_preflight(evidence: EvidenceCollector, live: bool) -> AcceptanceItem`.
- The preflight returns `BLOCKED` when `live` is false, `FAIL` on any Worker/model/Skill mismatch, and `PASS` only when the lock model and all six effective Worker models match and all required Skills are ready.
- `run_phase_one` runs preflight before `_a1_agentteams`; if it is not `PASS`, A1-A4 and live A6 must not dispatch external audits.

- [ ] **Step 1: Write failing preflight tests**

```python
def test_agentteams_preflight_fails_on_stale_model(monkeypatch, tmp_path):
    class Client:
        def get_workers(self, name=None):
            return [{"name": name, "phase": "Running", "model": "model"}]
        def get_worker_skill_observation(self, name):
            return {"skills": []}

    monkeypatch.setattr(phase_one, "HiclawClient", Client)
    item = phase_one._agentteams_preflight(fake_evidence(tmp_path), True)
    assert item.status == "FAIL"
    assert "effective_model=model" in item.detail


def test_phase_one_does_not_dispatch_when_preflight_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(phase_one, "_agentteams_preflight",
                        lambda evidence, live: AcceptanceItem("PREFLIGHT", "FAIL", "stale model"))
    monkeypatch.setattr(phase_one, "_a1_agentteams",
                        lambda *args: (_ for _ in ()).throw(AssertionError("A1 dispatched")))
    # Exercise run_phase_one with a temporary target and assert the report is rejected.
```

Use the existing evidence fixture/helper patterns in `tests/unit/test_acceptance_runner.py`; the test must not invoke Docker.

- [ ] **Step 2: Run preflight tests and confirm failure**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_acceptance_runner.py -q
```

Expected: FAIL because `_agentteams_preflight` is not defined and `run_phase_one` does not gate dispatch.

- [ ] **Step 3: Implement preflight using sanitized client state**

Load the locked model with `load_locked_model(Path("agentteams/contract.lock.json"))`. For each Worker in `WORKERS`, compare effective model, phase, and ready Skill names. Aggregate all mismatches into one detail string; do not include raw Worker JSON or environment values.

- [ ] **Step 4: Gate the live acceptance sequence**

In `run_phase_one`, insert the preflight before the existing item list. If it is `FAIL` or `BLOCKED`, create `BLOCKED` items for A1-A4 and preserve the existing local-only A5/A8 behavior; run local A6 only when appropriate, but never start live audit commands. Include the preflight item in the generated report and update A8’s generated acceptance text consistently.

- [ ] **Step 5: Run unit tests and commit**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_acceptance_runner.py tests/unit/test_model_config.py tests/unit/test_agentteams_worker_config.py -q
```

Expected: PASS.

```powershell
git add acceptance/phase_one.py tests/unit/test_acceptance_runner.py
git commit -m "test: gate live acceptance on effective Worker model"
```

---

## Task 6: Run repository verification before touching live containers

**Files:**
- No source changes expected.

- [ ] **Step 1: Check the working tree and preserve unrelated changes**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
git status --short
git diff --stat
```

Expected: only the planned source/test commits are new relative to the pre-existing dirty state; no unrelated file is reset or deleted.

- [ ] **Step 2: Run targeted and full local suites**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_model_config.py tests/unit/test_agentteams_worker_config.py tests/unit/test_agentteams_skill_lock.py tests/unit/test_acceptance_runner.py -q
python -m pytest -m "not agentteams" -q
```

Expected: both commands exit `0`. If an existing unrelated test fails, record the exact failure and do not claim the repair is verified.

- [ ] **Step 3: Validate the lock directly**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -c "from pathlib import Path; from agentteams.model_config import load_locked_model; print(load_locked_model(Path('agentteams/contract.lock.json')))"
```

Expected output:

```text
deepseek-v4-flash
```

- [ ] **Step 4: Handle verification findings without touching unrelated files**

Do not create a no-op commit. If verification exposes a source defect, return to the relevant task, add a regression test, fix it, and rerun that task’s tests before continuing. If verification exposes only a pre-existing unrelated failure, record its exact path and output and leave its files unchanged.

---

## Task 7: Apply the model configuration to all six live Workers

**Files:**
- Runtime only: AgentTeams Worker resources and containers.
- Evidence: `.argus/model-config/<timestamp>/` created by the synchronizer; no credentials may be stored.

- [ ] **Step 1: Capture a sanitized pre-change snapshot**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m agentteams.apply_worker_config --workspace . --timeout 300 --snapshot-only
```

Expected: snapshot written under `.argus/model-config/`; it lists only Worker names, phases, models, runtimes, images, and ready Skill names, with no key/token/password text.

- [ ] **Step 2: Apply the locked model and wait for convergence**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m agentteams.apply_worker_config --workspace . --timeout 600
```

Expected: exit `0`, JSON reports `model=deepseek-v4-flash`, and all six Workers are listed with healthy phase, matching model, and matching ready Skills.

- [ ] **Step 3: Independently verify runtime log model resolution**

Run a read-only log filter, not a full raw-log dump:

```powershell
$names = 'argus-dep','argus-code','argus-sec','argus-delivery','argus-meta','argus-synth'
foreach ($name in $names) {
  docker logs --since 10m "agentteams-worker-$name" 2>&1 |
    Select-String -Pattern 'embedded run start|rawError=400|model=model|deepseek-v4-flash'
}
```

Expected: no new `model=model` and no new Provider 400. Any existing historical lines must be separated from the post-apply window.

- [ ] **Step 4: Stop and report if effective state is wrong**

If any Worker still reports `model=model`, do not run A1-A8. Record the Worker name, expected model, effective model, phase, image, and last sanitized error. Do not guess at a tool-schema fix while the model gate is red.

---

## Task 8: Run model-only and tool-enabled smoke gates

**Files:**
- Runtime/evidence only; no source changes expected unless a gate exposes a tested defect.

- [ ] **Step 1: Run a model-only smoke request for each Worker**

Use each Worker's `roomID` from `docker exec agentteams-manager hiclaw get workers -o json` and `HiclawClient.send_project_message(room_id, "Reply with exactly ARGUS_MODEL_SMOKE_OK. Do not call tools.", [matrix_user_id])`. Record the dispatch UTC timestamp, then inspect only post-timestamp Worker log lines matching `embedded run start`, `ARGUS_MODEL_SMOKE_OK`, `rawError=400`, or `model=model`.

Record only Worker name, expected model, response status, and sanitized Provider status/reason. Do not put credentials or full session transcripts into the evidence directory.

Expected: all six Workers return `ARGUS_MODEL_SMOKE_OK`; every post-dispatch run starts with `model=deepseek-v4-flash`; no 400 and no `model=model` occur.

- [ ] **Step 2: Run the `argus-code` tool-enabled smoke task**

Dispatch `task-20260810-1015` or a fresh equivalent only after the model-only gate passes. Verify that `argus-code` can pull `shared/tasks/<id>/spec.md`, run `argus-code-rule-scan`, write `result.md`, publish it, and acknowledge completion.

Expected: successful result artifact in the expected MinIO path and no generic LLM failure.

- [ ] **Step 3: Diagnose any valid-model tool failure from raw Provider evidence**

If the tool-enabled gate fails while runtime logs show `model=deepseek-v4-flash`, collect the raw Provider status/reason and tool names/schema metadata without credentials. Only then classify it as a separate tool-schema problem. Do not modify the Gateway or add fallback behavior as part of this model repair.

---

## Task 9: Run complete live A1-A8 acceptance

**Files:**
- Runtime/evidence: `.argus/acceptance/<new-run-id>/`
- Generated deliverables: existing `acceptance.md` and reports, preserving history.

- [ ] **Step 1: Confirm the acceptance CLI and target are readable**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m cli.argus acceptance phase-one --help
Test-Path "E:\koubo"
```

Expected: the CLI lists `--agentteams-live` and `--leakage-e2e`; the remembered A4 target `E:\koubo` exists. If the target does not exist, stop and report the missing acceptance prerequisite instead of substituting another project.

- [ ] **Step 2: Execute A1-A8**

Run:

```powershell
Set-Location "E:\heishou\Argus v2"
python -m cli.argus acceptance phase-one --target "E:\koubo" --workspace-mode current-source --agentteams-live --leakage-e2e
```

Do not shorten the existing 1800-second live audit timeout.

Expected: a new `.argus/acceptance/<run-id>/acceptance.json` is generated and the report has all eight items `PASS`.

- [ ] **Step 3: Inspect every item and evidence count**

Read the new `acceptance.json`, `acceptance.md`, and sanitized evidence manifest. Confirm:

```text
A1 PASS
A2 PASS
A3 PASS
A4 PASS
A5 PASS
A6 PASS
A7 PASS
A8 PASS
```

Also confirm the new evidence has no `model=model`, no raw credentials, and no canary leakage.

- [ ] **Step 4: Report truthfully**

If any item fails, report the exact item, command exit code, pytest counts, and sanitized evidence path. Do not claim completion or passing A1-A8 until all eight are `PASS`.

---

## Task 10: Final verification and handoff

**Files:**
- No source changes expected.
- Read: `docs/superpowers/specs/2026-08-10-agentteams-model-configuration-design.md`

- [ ] **Step 1: Run final focused checks**

```powershell
Set-Location "E:\heishou\Argus v2"
python -m pytest tests/unit/test_model_config.py tests/unit/test_agentteams_worker_config.py tests/unit/test_agentteams_skill_lock.py tests/unit/test_acceptance_runner.py -q
```

Expected: PASS.

- [ ] **Step 2: Capture final repository state**

```powershell
git status --short
git log -8 --oneline --decorate
```

Do not clean or reset unrelated dirty files.

- [ ] **Step 3: Provide the handoff**

Report the implementation commits, the final Worker model verification, smoke-gate results, the new A1-A8 run ID, all item statuses, and any remaining limitations. Distinguish source-test success from live-runtime success.
