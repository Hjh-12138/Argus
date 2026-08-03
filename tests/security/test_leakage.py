import json
from pathlib import Path

from core.report import write_report
from core.tracing import TraceRecorder

REPO = Path(__file__).resolve().parents[2]
CANARY = "sk-test-canary-1234567890abcdef"
PRIVATE_KEYS = (
    "private_reasoning", "reasoning_text", "raw_prompt", "raw_response",
    "source_code",
)


def _argus_text_artifacts():
    root = REPO / ".argus"
    if not root.exists():
        return []
    return [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix in (".json", ".md", ".jsonl", ".txt")
    ]


def test_report_and_trace_producers_remove_canary_and_private_fields(tmp_path):
    artifact_root = tmp_path / ".argus"
    report = {
        "schema_version": "2.0",
        "run_id": "leak-test",
        "run_status": "completed",
        "release_gate": "pass",
        "target": {"snapshot_id": "a" * 64},
        "findings": [],
        "policy_decisions": [{"reasons": []}],
        "coverage": {"files_scanned": 0, "files_total": 0,
                     "agents_completed": []},
        "versions": {"argus": "2.0.0", "rules": "test"},
        "errors": [{"message": f"api_key={CANARY}"}],
        "private_reasoning": "hidden",
    }
    write_report(artifact_root / "reports", report)

    recorder = TraceRecorder()
    trace_id = recorder.new_trace("leak-test", "snapshot", "project")
    span_id = recorder.start_span(trace_id, "model", "llm_call")
    recorder.record_event(trace_id, span_id, "completed", {
        "api_key": CANARY,
        "raw_prompt": "hidden",
        "duration_ms": 1,
    })
    recorder.flush_to_jsonl(artifact_root / "trace.jsonl")

    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in artifact_root.rglob("*") if path.is_file()
    )
    assert CANARY not in text
    for key in PRIVATE_KEYS:
        assert key not in text


def test_no_secret_in_reports_or_trace():
    for path in _argus_text_artifacts():
        text = path.read_text(encoding="utf-8", errors="replace")
        assert CANARY not in text, f"secret leaked in {path}"


def test_no_private_reasoning_keys():
    for path in _argus_text_artifacts():
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in PRIVATE_KEYS:
            assert key not in text, f"private field {key} leaked in {path}"
