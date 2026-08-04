"""Sanitized command results and the exact evidence manifest."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from core.sanitizer import Sanitizer

_SANITIZER = Sanitizer()


class EvidenceCollector:
    def __init__(self, root: Path):
        self.root = root
        self.command_results = root / "command-results"
        self.sanitized_excerpts = root / "sanitized-excerpts"
        self.manifest: dict = {"resources": [], "commands": []}
        for directory in (self.command_results, self.sanitized_excerpts):
            directory.mkdir(parents=True, exist_ok=True)

    def run_command(self, name: str, argv: list[str], *, timeout: int = 300,
                    env: dict | None = None) -> dict:
        """Run a command and return {exit, duration_s, stdout, stderr}.

        Only sanitized excerpts are persisted to the evidence manifest; raw
        stdout/stderr are returned to the caller (e.g. for leak scanning or
        suite-count parsing) but never written to disk as evidence.
        """
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=timeout, env=env)
            result = {
                "command": name, "exit": proc.returncode,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout": proc.stdout, "stderr": proc.stderr,
            }
            if proc.stdout.strip():
                excerpt = self.sanitized_excerpts / f"{name}.stdout.txt"
                excerpt.write_text(_SANITIZER.sanitize_text(proc.stdout)[:4000],
                                   encoding="utf-8")
                result["stdout_excerpt"] = str(excerpt)
            if proc.stderr.strip():
                excerpt = self.sanitized_excerpts / f"{name}.stderr.txt"
                excerpt.write_text(_SANITIZER.sanitize_text(proc.stderr)[:4000],
                                   encoding="utf-8")
                result["stderr_excerpt"] = str(excerpt)
        except subprocess.TimeoutExpired:
            result = {"command": name, "exit": -1,
                      "duration_s": round(time.monotonic() - started, 3),
                      "timed_out": True, "stdout": "", "stderr": ""}
        manifest_entry = {key: value for key, value in result.items()
                          if key not in ("stdout", "stderr")}
        self.manifest["commands"].append(manifest_entry)
        return result

    def add_resource(self, kind: str, name: str, digest: str = "") -> None:
        self.manifest["resources"].append({
            "kind": kind, "name": name, "digest": digest,
        })

    def write(self, name: str = "evidence-manifest.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path
