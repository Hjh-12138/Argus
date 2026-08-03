"""最小结构化 trace recorder：allowlist、敏感字段过滤、JSONL 落盘。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ALLOWED_EVENTS = {
    "scheduled", "started", "retrying", "cache_hit", "finding_emitted",
    "evidence_checked", "meta_decided", "gate_decided", "budget_reached",
    "fallback_activated", "cancel_requested", "completed", "failed",
}
_FORBIDDEN_KEYS = {
    "reasoning_text", "raw_prompt", "raw_response", "source_code",
    "secret", "api_key", "private_reasoning",
}
_ALLOWED_SPANS = {
    ("controller", "audit"),
    ("model", "llm_call"),
    ("tool", "scan"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceRecorder:
    def __init__(self):
        self.traces: dict[str, dict] = {}
        self.records: list[dict] = []
        self.last_attrs: dict = {}

    def new_trace(self, run_id: str, snapshot_id: str,
                  project_scope: str) -> str:
        trace_id = str(uuid.uuid4())
        self.traces[trace_id] = {
            "trace_id": trace_id,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "project_scope_id": project_scope,
            "sampling_decision": "full",
            "created_at": _now(),
        }
        return trace_id

    def start_span(self, trace_id: str, kind: str,
                   operation_name: str) -> str:
        if trace_id not in self.traces:
            raise ValueError("unknown trace_id")
        if (kind, operation_name) not in _ALLOWED_SPANS:
            raise ValueError(f"unregistered span: {kind}/{operation_name}")
        span_id = str(uuid.uuid4())
        self.records.append({
            "trace_id": trace_id,
            "span_id": span_id,
            "kind": kind,
            "operation_name": operation_name,
            "status": "unset",
            "started_at": _now(),
        })
        return span_id

    def record_event(self, trace_id: str, span_id: str,
                     event_type: str, attrs: dict) -> None:
        if event_type not in _ALLOWED_EVENTS:
            return
        clean = {
            key: value for key, value in attrs.items()
            if key not in _FORBIDDEN_KEYS
            and isinstance(value, (int, float, str, bool))
        }
        self.last_attrs = clean
        self.records.append({
            "trace_id": trace_id,
            "span_id": span_id,
            "event": event_type,
            "attributes": clean,
            "ts": _now(),
        })

    def finish_span(self, trace_id: str, span_id: str,
                    status: str) -> None:
        for record in self.records:
            if (record.get("trace_id") == trace_id
                    and record.get("span_id") == span_id
                    and "status" in record):
                record["status"] = status
                record["finished_at"] = _now()
                return

    def flush_to_jsonl(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for trace in self.traces.values():
                handle.write(json.dumps({
                    **trace,
                    "record_type": "trace",
                }, ensure_ascii=False) + "\n")
            for record in self.records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
