import json

from core.tracing import TraceRecorder


def test_trace_records_structured_events(tmp_path):
    recorder = TraceRecorder()
    trace_id = recorder.new_trace(
        run_id="r1", snapshot_id="s1", project_scope="p1")
    span_id = recorder.start_span(trace_id, "controller", "audit")
    recorder.record_event(
        trace_id, span_id, "scheduled", {"agents": "dep,sec"})
    recorder.finish_span(trace_id, span_id, "ok")
    recorder.flush_to_jsonl(tmp_path / "trace.jsonl")

    lines = (tmp_path / "trace.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert lines
    event = json.loads(lines[1])
    assert event["trace_id"] == trace_id
    assert event["span_id"] == span_id
    assert event["event"] == "scheduled"
    assert event["attributes"] == {"agents": "dep,sec"}


def test_private_fields_forbidden():
    recorder = TraceRecorder()
    trace_id = recorder.new_trace(
        run_id="r", snapshot_id="s", project_scope="p")
    span_id = recorder.start_span(trace_id, "model", "llm_call")

    recorder.record_event(trace_id, span_id, "completed", {
        "reasoning_text": "hidden-chain-of-thought",
        "raw_prompt": "private prompt",
        "api_key": "sk-test-canary-1234567890abcdef",
        "duration_ms": 12,
    })

    assert recorder.last_attrs == {"duration_ms": 12}


def test_unknown_events_and_nested_attributes_are_not_recorded():
    recorder = TraceRecorder()
    trace_id = recorder.new_trace(
        run_id="r", snapshot_id="s", project_scope="p")
    span_id = recorder.start_span(trace_id, "tool", "scan")
    before = len(recorder.records)

    recorder.record_event(
        trace_id, span_id, "arbitrary_event", {"source": ["raw"]})

    assert len(recorder.records) == before
