"""Delivery Auditor：CI 有测试文件但工作流仅构建、不运行测试。"""
from __future__ import annotations

import re
from pathlib import Path

from core.redaction import hmac_fingerprint
from core.schemas import Evidence, Finding, SourceSnapshot

_FINGERPRINT_SALT = b"argus-delivery-salt"
TEST_RUN = re.compile(r"(?i)\b(pytest|python\s+-m\s+unittest|go\s+test|npm\s+test|pnpm\s+test|yarn\s+test|dotnet\s+test|mvn\s+test|gradle\s+test|make\s+test)\b")
COMPILE_OR_BUILD = re.compile(r"(?i)(compileall|tsc\s+--noEmit|go\s+build|npm\s+run\s+build|pnpm\s+build|mvn\s+package|gradle\s+build)")


class DeliveryDetector:
    def detect(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        has_tests = any(_is_test_path(sf.path) for sf in snapshot.files)
        if not has_tests:
            return ()
        out: list[Finding] = []
        for sf in snapshot.files:
            if not _is_ci_path(sf.path):
                continue
            text = self._read(snapshot.root, sf.path)
            if COMPILE_OR_BUILD.search(text) and not TEST_RUN.search(text):
                out.append(Finding(
                    id=f"delivery-testgap-{sf.path}",
                    agent="delivery",
                    category="delivery.test_gap",
                    severity="medium",
                    confidence=0.88,
                    title="CI builds the project but does not run tests",
                    detail="The repository contains tests, but this CI workflow has no test command",
                    file=sf.path,
                    line_start=1,
                    line_end=1,
                    remediation="add the repository's test command to the CI workflow",
                    verification="inspect the updated workflow and rerun Delivery Auditor",
                    rollback=None,
                    cwe=None,
                    fingerprint=hmac_fingerprint(
                        f"delivery.testgap:{sf.path}", _FINGERPRINT_SALT),
                    rule_id="DEL-001",
                    rule_version="1",
                    evidence=Evidence(
                        context_lines=("CI workflow contains build/compile but no test command",),
                        source_sha256=sf.sha256,
                        redacted_value=None,
                        detector="delivery.ci-policy-check",
                        reasoning_summary=None,
                    ),
                ))
        return tuple(out)

    def _read(self, root: str, path: str) -> str:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")


def _is_ci_path(path: str) -> bool:
    p = path.lower()
    return (
        p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ) or p in (".gitlab-ci.yml", "azure-pipelines.yml")


def _is_test_path(path: str) -> bool:
    p = "/" + path.lower()
    return (
        "/tests/" in p
        or "/test/" in p
        or "/__tests__/" in p
        or ".test." in p
        or ".spec." in p
        or path.lower().startswith(("test_", "tests/", "test/"))
    )
