from pathlib import Path

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


def test_no_secret_in_reports_or_trace():
    for path in _argus_text_artifacts():
        text = path.read_text(encoding="utf-8", errors="replace")
        assert CANARY not in text, f"secret leaked in {path}"


def test_no_private_reasoning_keys():
    for path in _argus_text_artifacts():
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in PRIVATE_KEYS:
            assert key not in text, f"private field {key} leaked in {path}"
