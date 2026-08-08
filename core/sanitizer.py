"""Sanitize command output for evidence manifests.

Redacts paths, tokens, secrets, and other sensitive content from
command stdout/stderr before writing to acceptance evidence.
"""
from __future__ import annotations

import os
import re


class Sanitizer:
    """Redact sensitive content from text output."""

    def __init__(self):
        home = os.path.expanduser("~")
        self._patterns = [
            # Home directory
            (re.compile(re.escape(home)), "~"),
            # Windows-style paths
            (re.compile(r"[A-Z]:\\Users\\[^\s,;]+"), "<redacted-path>"),
            # API keys and tokens
            (re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})\b"),
             "[REDACTED]"),
            # JWT tokens
            (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
             "[REDACTED-JWT]"),
            # Passwords in key=value pairs
            (re.compile(r'(?i)(password|secret|token|key)\s*=\s*[^\s,;]+'),
             r'\1=<redacted>'),
        ]

    def sanitize_text(self, text: str) -> str:
        """Apply all redaction patterns to text."""
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text
