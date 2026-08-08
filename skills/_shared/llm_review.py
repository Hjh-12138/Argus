#!/usr/bin/env python3
"""Shared LLM review helper — calls AI Gateway for semantic code analysis.

Import from any skill via:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '_shared'))
    from llm_review import review_finding

Uses only stdlib (urllib, json, os). No external dependencies.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

# Default AI Gateway configuration
_GATEWAY_URL = os.environ.get(
    "ARGUS_AI_GATEWAY_URL",
    "http://agentteams-controller:8080/v1",
)
_DEFAULT_MODEL = os.environ.get("ARGUS_REVIEW_MODEL", "deepseek-chat")

_REVIEW_SYSTEM_PROMPT = """You are a code audit expert. Review the following finding and its code context.

Determine if this is a REAL issue that requires attention.

Rules:
- If the finding correctly identifies a genuine risk, reply YES.
- If the finding is a false positive (code is safe in context), reply NO.
- If the code is auto-generated, test code, or config boilerplate, lean toward NO.
- Consider the actual usage context, not just the pattern match.

Reply in JSON format:
{"verdict": "YES" or "NO", "confidence": 0.0-1.0, "reason": "one sentence explaining why"}"""


def _load_gateway_key() -> str:
    """Load the AI Gateway API key from the worker's openclaw.json."""
    worker_name = os.environ.get("AGENTTEAMS_WORKER_NAME", "")
    config_paths = [
        Path(f"/root/hiclaw-fs/agents/{worker_name}/openclaw.json"),
        Path.home() / ".openclaw" / "openclaw.json",
    ]
    for config_path in config_paths:
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                providers = config.get("models", {}).get("providers", {})
                for provider in providers.values():
                    key = provider.get("apiKey", "")
                    if key:
                        return key
            except (json.JSONDecodeError, OSError):
                continue
    return os.environ.get("AGENTTEAMS_GATEWAY_KEY", "")


def review_finding(
    finding: dict,
    code_context: str = "",
    *,
    model: str | None = None,
    timeout_s: int = 15,
) -> dict:
    """Ask the LLM to review a single finding with its code context.

    Args:
        finding: The finding dict (must have title, detail, file, severity, category).
        code_context: The relevant source code around the finding location.
        model: Model to use (default: deepseek-chat).
        timeout_s: HTTP timeout in seconds.

    Returns:
        {"verdict": "YES"|"NO", "confidence": 0.0-1.0, "reason": str}
        On failure: {"verdict": "ERROR", "confidence": 0.0, "reason": "<error message>"}
    """
    api_key = _load_gateway_key()
    if not api_key:
        return {"verdict": "ERROR", "confidence": 0.0,
                "reason": "AI Gateway API key not found"}

    severity = finding.get("severity", "unknown")
    category = finding.get("category", "unknown")
    title = finding.get("title", "Untitled")
    detail = finding.get("detail", "")
    file_path = finding.get("file", "unknown")
    line = finding.get("line_start", "?")

    user_message = (
        f"Finding: [{severity.upper()}] {title}\n"
        f"Category: {category}\n"
        f"File: {file_path}:{line}\n"
        f"Detail: {detail}\n"
    )
    if code_context:
        max_context = 4000  # ~1K tokens
        if len(code_context) > max_context:
            code_context = code_context[:max_context] + "\n... (truncated)"
        user_message += f"\nCode context:\n```\n{code_context}\n```"

    body = json.dumps({
        "model": model or _DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
    }).encode("utf-8")

    url = f"{_GATEWAY_URL.rstrip('/')}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return {"verdict": "ERROR", "confidence": 0.0,
                "reason": f"LLM call failed: {exc}"}

    try:
        content = raw["choices"][0]["message"]["content"]
        # Parse the JSON response from the LLM
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        result = json.loads(content)
        return {
            "verdict": str(result.get("verdict", "ERROR")).upper(),
            "confidence": float(result.get("confidence", 0.0)),
            "reason": str(result.get("reason", "")),
        }
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        return {"verdict": "ERROR", "confidence": 0.0,
                "reason": f"Failed to parse LLM response: {exc}"}


def review_findings_batch(
    findings: list[dict],
    code_contexts: dict[str, str] | None = None,
    *,
    model: str | None = None,
) -> list[dict]:
    """Review multiple findings. Each finding gets its own LLM call.

    Args:
        findings: List of finding dicts.
        code_contexts: Dict of file_path -> code_context string.
        model: Model override.

    Returns:
        List of review results (same order as input).
    """
    contexts = code_contexts or {}
    results = []
    for finding in findings:
        ctx = contexts.get(finding.get("file", ""), "")
        results.append(review_finding(finding, ctx, model=model))
    return results
