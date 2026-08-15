"""Host-side adapter: shared maintainability rules -> schema Finding.

Rules live in the standalone skill module; this bridge converts RuleHit to
Finding so the deterministic local engine reports the same findings as the
AgentTeams skill. Uses sys.path so the host can import the pure-stdlib rules
module without coupling packages (the skill stays standalone).
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.redaction import hmac_fingerprint
from core.schemas import Evidence, Finding, SourceSnapshot

_SALT = b"argus-code-maintainability-salt"
_rules_dir = (Path(__file__).resolve().parents[2]
              / "skills" / "argus-code-maintainability-scan" / "implementation")
if str(_rules_dir) not in sys.path:
    sys.path.insert(0, str(_rules_dir))
from rules import RuleHit, scan_path  # noqa: E402


def scan_snapshot(snapshot: SourceSnapshot) -> tuple[Finding, ...]:
    out: list[Finding] = []
    for sf in snapshot.files:
        if not sf.path.endswith(".py"):
            continue
        text = (Path(snapshot.root) / sf.path).read_text(encoding="utf-8",
                                                         errors="replace")
        for hit in scan_path(sf.path, text):
            out.append(_to_finding(sf, hit))
    return tuple(out)


def _to_finding(sf, hit: RuleHit) -> Finding:
    return Finding(
        id=f"{hit.category}-{sf.path}:{hit.line_start}",
        agent="code",
        category=hit.category,
        severity=hit.severity,
        confidence=hit.confidence,
        title=hit.title,
        detail=hit.detail,
        remediation=hit.remediation,
        verification="rerun Code Auditor on the new snapshot",
        fingerprint=hmac_fingerprint(
            f"{hit.category}:{sf.path}:{hit.line_start}", _SALT),
        rule_id=hit.rule_id,
        rule_version="1",
        file=sf.path,
        line_start=hit.line_start,
        line_end=hit.line_end,
        rollback=None,
        cwe=None,
        evidence=Evidence(
            context_lines=(hit.excerpt,),
            source_sha256=sf.sha256,
            redacted_value=None,
            detector=f"code.{hit.category.split('.')[-1]}-detect",
            reasoning_summary=None,
        ),
    )
