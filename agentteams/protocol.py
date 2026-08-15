"""Strict typed models and parsers for the AgentTeams Task protocol v1.

Parsing rejects unknown states, missing revisions, non-SHA digests, absolute
input paths, and result references outside tasks/<task-id>/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    REGISTERED = "REGISTERED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REVISION_NEEDED = "REVISION_NEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CONFLICT = "CONFLICT"
    HUMAN_WAIT = "HUMAN_WAIT"


TERMINAL_STATES = {
    TaskState.COMPLETED, TaskState.REVISION_NEEDED, TaskState.BLOCKED,
    TaskState.FAILED, TaskState.TIMED_OUT, TaskState.CONFLICT,
}

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,127}$")
_SHA_PATTERN = re.compile(r"^(sha256:)?[0-9a-f]{64}$")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class FileDigest:
    path: str
    sha256: str


@dataclass(frozen=True)
class TaskEnvelope:
    schema_version: str
    task_id: str
    project_id: str
    assigned_worker: str
    kind: str
    attempt: int
    deadline: datetime
    skill: str
    skill_version: str
    skill_generation: str
    skill_digest: str
    agent_version: str
    inputs: tuple[FileDigest, ...] = ()
    input_payload: dict[str, Any] = field(default_factory=dict)
    output_schema: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    assigned_worker: str
    state: TaskState
    revision: int
    attempt: int
    required: bool
    idempotency_key: str
    request_digest: str = ""
    dispatch_count: int = 0
    result_digest: str = ""
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class TaskResultRef:
    task_id: str
    result_digest: str
    artifact_path: str


def parse_record(raw: dict) -> TaskRecord:
    task_id = raw.get("task_id")
    if not _ID_PATTERN.fullmatch(str(task_id or "")):
        raise ProtocolError(f"invalid task_id: {task_id!r}")
    state_raw = raw.get("state")
    try:
        state = TaskState(state_raw)
    except ValueError:
        raise ProtocolError(f"unknown task state: {state_raw!r}")
    revision = raw.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ProtocolError(f"missing or invalid revision: {revision!r}")
    return TaskRecord(
        task_id=task_id,
        assigned_worker=str(raw.get("assigned_worker", "")),
        state=state,
        revision=revision,
        attempt=int(raw.get("attempt", 1)),
        required=bool(raw.get("required", True)),
        idempotency_key=str(raw.get("idempotency_key", "")),
        request_digest=str(raw.get("request_digest", "")),
        dispatch_count=int(raw.get("dispatch_count", 0)),
        result_digest=str(raw.get("result_digest", "")),
        error_code=str(raw.get("error_code", "")),
        error_message=str(raw.get("error_message", "")),
    )


def parse_envelope(raw: dict) -> TaskEnvelope:
    task_id = raw.get("task_id")
    if not _ID_PATTERN.fullmatch(str(task_id or "")):
        raise ProtocolError(f"invalid task_id: {task_id!r}")
    deadline_raw = raw.get("deadline")
    if not deadline_raw:
        raise ProtocolError("missing deadline")
    try:
        deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
    except ValueError:
        raise ProtocolError(f"invalid deadline: {deadline_raw!r}")
    skill_digest = str(raw.get("skill_digest", ""))
    if not _SHA_PATTERN.fullmatch(skill_digest):
        raise ProtocolError(f"invalid skill_digest: {skill_digest!r}")

    inputs: list[FileDigest] = []
    for item in raw.get("inputs", []):
        path = str(item.get("path", ""))
        digest = str(item.get("sha256", ""))
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ProtocolError(f"unsafe input path: {path!r}")
        if not _SHA_PATTERN.fullmatch(digest):
            raise ProtocolError(f"invalid input sha256: {digest!r}")
        inputs.append(FileDigest(path=path, sha256=digest))

    output_schema = str(raw.get("output_schema", ""))
    if output_schema and not output_schema.startswith("skills/"):
        raise ProtocolError(f"unsafe output schema path: {output_schema!r}")

    return TaskEnvelope(
        schema_version=str(raw.get("schema_version", "1")),
        task_id=task_id,
        project_id=str(raw.get("project_id", "")),
        assigned_worker=str(raw.get("assigned_worker", "")),
        kind=str(raw.get("kind", "")),
        attempt=int(raw.get("attempt", 1)),
        deadline=deadline,
        skill=str(raw.get("skill", "")),
        skill_version=str(raw.get("skill_version", "")),
        skill_generation=str(raw.get("skill_generation", "")),
        skill_digest=skill_digest,
        agent_version=str(raw.get("agent_version", "")),
        inputs=tuple(inputs),
        input_payload=raw.get("input_payload", {}) or {},
        output_schema=output_schema,
        idempotency_key=str(raw.get("idempotency_key", "")),
    )


def parse_result_ref(raw: dict, task_id: str) -> TaskResultRef:
    result_digest = str(raw.get("result_digest", ""))
    artifact_path = str(raw.get("artifact_path", ""))
    expected_prefix = f"tasks/{task_id}/artifacts/"
    if not artifact_path.startswith(expected_prefix):
        raise ProtocolError(f"result ref outside tasks/<id>: {artifact_path!r}")
    if not _SHA_PATTERN.fullmatch(result_digest):
        raise ProtocolError(f"invalid result_digest: {result_digest!r}")
    return TaskResultRef(task_id=task_id, result_digest=result_digest,
                         artifact_path=artifact_path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
