"""Code Auditor：占位实现检测 + 可维护性审查（初赛最小规则集）。"""
from __future__ import annotations

import re
from pathlib import Path

from core.redaction import hmac_fingerprint, redact
from core.schemas import Evidence, Finding, SourceSnapshot
from agents.code.maintainability import scan_snapshot

_FINGERPRINT_SALT = b"argus-code-salt"
_SOURCE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs")
PLACEHOLDER = re.compile(
    r"(?i)(TODO\s*:?\s*implement|FIXME\s*:?\s*implement|"
    r"return\s+['\"]?not\s+implemented|raise\s+NotImplementedError|"
    r"placeholder\s+implementation)"
)


class CodeDetector:
    def detect(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        out = list(self._placeholder_findings(snapshot))
        out.extend(scan_snapshot(snapshot))
        return tuple(out)

    def _placeholder_findings(self, snapshot: SourceSnapshot) -> tuple[Finding, ...]:
        # 原 detect() 的占位符逻辑原样搬到这里
        out: list[Finding] = []
        for sf in snapshot.files:
            if not sf.path.endswith(_SOURCE_EXTS):
                continue
            text = self._read(snapshot.root, sf.path)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if not PLACEHOLDER.search(line):
                    continue
                excerpt = redact(line.strip()[:300])
                out.append(Finding(
                    id=f"code-placeholder-{sf.path}:{line_no}",
                    agent="code", category="code.placeholder",
                    severity="medium", confidence=0.82,
                    title="Placeholder implementation remains in production code",
                    detail="A placeholder marker indicates incomplete behavior",
                    file=sf.path, line_start=line_no, line_end=line_no,
                    remediation="replace the placeholder with a complete implementation",
                    verification="rerun Code Auditor on the new snapshot",
                    rollback=None, cwe=None,
                    fingerprint=hmac_fingerprint(
                        f"code.placeholder:{sf.path}:{line_no}", _FINGERPRINT_SALT),
                    rule_id="CODE-001", rule_version="1",
                    evidence=Evidence(
                        context_lines=(excerpt,),
                        source_sha256=sf.sha256,
                        redacted_value=None,
                        detector="code.placeholder-detect",
                        reasoning_summary=None,
                    ),
                ))
        return tuple(out)

    def _read(self, root: str, path: str) -> str:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")
