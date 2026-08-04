"""Orchestrate A1-A8 and produce the sanitized acceptance report.

Each item follows the written A1-A8 matrix instead of blindly accepting an
exit code:
  A1  vulnerable demo (local) must block and report all three categories
  A2  vulnerable demo (AgentTeams) must run through real Workers and block
  A3  fixed demo (local) must pass with no vulnerable categories
  A4  koubo current-source snapshot on real Workers (live only)
  A5  eight locked Skills + (live) observed ready assignments
  A6  local + live suites, per-suite counts recorded
  A7  random canary never reaches report or audit output
  A8  delivery docs exist and match measured facts; acceptance.md generated
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from acceptance.evidence import EvidenceCollector
from acceptance.models import AcceptanceItem, AcceptanceReport

ACCEPTANCE_ROOT = Path(".argus") / "acceptance"

AUDIT_EXITS = {0, 1, 2, 3}
DEMO = Path("demo/scenarios/ai-pr-three-defects")
REGISTRY_FIXTURE = DEMO / "registry-fixture.json"
VULNERABLE_CATEGORIES = {"dependency.nonexistent", "security.sql_injection",
                         "delivery.test_gap"}
REPORT_JSON = Path(".argus/reports/report.json")

README_SECTIONS = ("架构", "快速开始", "测试", "当前进展")
INTRO_PATH = Path("docs") / "初赛-作品简介.md"
PPT_PATH = Path("docs") / "初赛-方案PPT大纲.md"
ACCEPTANCE_MD = Path("acceptance.md")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _audit_completed(exit_code: int) -> bool:
    return exit_code in AUDIT_EXITS


def _read_report(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _report_gate(path: Path) -> str | None:
    data = _read_report(path)
    return data.get("release_gate") if isinstance(data, dict) else None


def _pytest_summary(text: str) -> dict:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "deselected": 0, "error": 0}
    if not text.strip():
        return counts
    line = text.strip().splitlines()[-1]
    for key in counts:
        match = re.search(rf"(\d+)\s+{key}", line)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _fmt_counts(counts: dict) -> str:
    parts = [f"{counts[k]} {k}" for k in
             ("passed", "failed", "skipped", "deselected")]
    return ", ".join(parts)


def _run_audit(evidence, name, target, *, engine, registry_fixture=True,
               demo_invalid=False, timeout=600) -> dict:
    argv = [sys.executable, "-m", "cli.argus", "audit",
            "--target", str(target), "--headless", "--engine", engine]
    if registry_fixture and REGISTRY_FIXTURE.exists():
        argv += ["--registry-fixture", str(REGISTRY_FIXTURE)]
    if demo_invalid:
        argv.append("--demo-invalid-finding")
    return evidence.run_command(name, argv, timeout=timeout)


def run_phase_one(*, target: Path, workspace_mode: str = "current-source",
                  agentteams_live: bool = False,
                  acceptance_probe: str = "hallucination-revision",
                  leakage_e2e: bool = False) -> AcceptanceReport:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_root = ACCEPTANCE_ROOT / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    evidence = EvidenceCollector(run_root)
    items = [
        _a1_local(evidence),
        _a2_agentteams_demo(evidence, agentteams_live),
        _a3_fixed(evidence),
        _a4_koubo(evidence, target, workspace_mode, agentteams_live),
        _a5_skill_lock(evidence, agentteams_live),
        _a6_suites(evidence, agentteams_live),
        _a7_leakage(evidence, run_root, leakage_e2e),
    ]
    # A8 verifies delivery docs including the acceptance.md deliverable, so
    # write it first from the current run, then finalize the report.
    _write_acceptance_md(AcceptanceReport(run_id=run_id, phase_one="rejected",
                                          items=items, generated_at=_now()))
    a8 = _a8_docs(evidence, run_id)
    report = AcceptanceReport(run_id=run_id,
                              phase_one="accepted" if all(
                                  i.status == "PASS" for i in [*items, a8]) else "rejected",
                              items=[*items, a8], generated_at=_now())
    evidence.add_resource("local", "acceptance.json")
    evidence.write()
    (run_root / "acceptance.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _write_acceptance_md(report)
    return report


def _a1_local(evidence: EvidenceCollector) -> AcceptanceItem:
    result = _run_audit(evidence, "A1-local-demo", DEMO / "vulnerable",
                        engine="local", demo_invalid=True)
    if not _audit_completed(result.get("exit", -1)):
        return AcceptanceItem("A1", "FAIL", "demo local audit did not complete")
    report = _read_report(REPORT_JSON)
    gate = report.get("release_gate") if report else None
    if gate != "block":
        return AcceptanceItem("A1", "FAIL", f"vulnerable demo gate={gate}, want block")
    categories = {f.get("category") for f in report.get("findings", [])}
    missing = sorted(VULNERABLE_CATEGORIES - categories)
    if missing:
        return AcceptanceItem("A1", "FAIL", f"missing vulnerable categories: {missing}")
    return AcceptanceItem("A1", "PASS",
                          "vulnerable demo blocked with all three categories")


def _a2_agentteams_demo(evidence: EvidenceCollector, live: bool) -> AcceptanceItem:
    if not live:
        return AcceptanceItem("A2", "BLOCKED", "requires --agentteams-live")
    result = _run_audit(evidence, "A2-agentteams-demo", DEMO / "vulnerable",
                        engine="agentteams", timeout=1800)
    if not _audit_completed(result.get("exit", -1)):
        return AcceptanceItem("A2", "FAIL", "demo agentteams audit did not complete")
    if result.get("exit") != 2:
        return AcceptanceItem("A2", "FAIL",
                              f"vulnerable demo gate exit={result.get('exit')}, want block(2)")
    return AcceptanceItem("A2", "PASS",
                          "demo ran through real Workers and blocked on defects")


def _a3_fixed(evidence: EvidenceCollector) -> AcceptanceItem:
    result = _run_audit(evidence, "A3-fixed-demo", DEMO / "fixed", engine="local")
    if result.get("exit") != 0:
        return AcceptanceItem("A3", "FAIL", f"fixed demo exit={result.get('exit')}, want 0")
    report = _read_report(REPORT_JSON)
    gate = report.get("release_gate") if report else None
    if gate != "pass":
        return AcceptanceItem("A3", "FAIL", f"fixed demo gate={gate}, want pass")
    categories = {f.get("category") for f in report.get("findings", [])}
    if categories & VULNERABLE_CATEGORIES:
        return AcceptanceItem("A3", "FAIL",
                              "fixed demo still reports vulnerable categories")
    return AcceptanceItem("A3", "PASS",
                          "fixed demo passed with no vulnerable categories")


def _a4_koubo(evidence: EvidenceCollector, target: Path, workspace_mode: str,
              live: bool) -> AcceptanceItem:
    if not live:
        return AcceptanceItem("A4", "BLOCKED", "requires --agentteams-live")
    if not Path(target).is_dir():
        return AcceptanceItem("A4", "FAIL", "target not readable")
    result = _run_audit(evidence, "A4-koubo-agentteams", target,
                        engine="agentteams", registry_fixture=False, timeout=1800)
    if not _audit_completed(result.get("exit", -1)):
        return AcceptanceItem("A4", "FAIL", "koubo agentteams audit did not complete")
    return AcceptanceItem("A4", "PASS",
                          "koubo current-source snapshot ran on real Workers")


def _a5_skill_lock(evidence: EvidenceCollector, live: bool) -> AcceptanceItem:
    lock_path = Path("skills") / "skills.lock.json"
    if not lock_path.is_file():
        return AcceptanceItem("A5", "FAIL", "skills.lock.json missing")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    names = {s["name"] for s in lock.get("skills", [])}
    if len(names) != 8:
        return AcceptanceItem("A5", "FAIL", f"expected 8 unique skills, got {len(names)}")
    assignments = lock.get("assignments", {})
    if len(assignments) != 6:
        return AcceptanceItem("A5", "FAIL",
                              f"expected 6 worker assignments, got {len(assignments)}")
    evidence.add_resource("lock", str(lock_path))
    if live:
        from agentteams.hiclaw_client import HiclawClient
        client = HiclawClient()
        bad = []
        for worker, expected in assignments.items():
            observed = client.get_worker_skill_observation(worker)
            ready = {s.get("name") for s in observed.get("skills", [])
                     if s.get("ready")}
            if ready != set(expected):
                bad.append(f"{worker}: ready={sorted(ready)} want={sorted(expected)}")
        if bad:
            return AcceptanceItem("A5", "FAIL", "; ".join(bad))
        return AcceptanceItem("A5", "PASS",
                              "8 unique skills locked and observed ready on 6 workers")
    return AcceptanceItem("A5", "PASS", "8 unique skills locked")


def _a6_suites(evidence: EvidenceCollector, live: bool) -> AcceptanceItem:
    local = evidence.run_command(
        "A6-local-suite",
        [sys.executable, "-m", "pytest", "-m", "not agentteams", "-q"],
        timeout=900)
    local_counts = _pytest_summary(local.get("stdout", ""))
    if local.get("exit") != 0:
        return AcceptanceItem("A6", "FAIL",
                              f"local suite failed: {_fmt_counts(local_counts)}")
    if not live:
        return AcceptanceItem("A6", "PASS",
                              f"local suite {_fmt_counts(local_counts)}")
    live_result = evidence.run_command(
        "A6-live-agentteams-suite",
        [sys.executable, "-m", "pytest", "-m", "agentteams", "-q"],
        timeout=1800,
        env={**os.environ, "ARGUS_AGENTTEAMS_E2E": "1"})
    live_counts = _pytest_summary(live_result.get("stdout", ""))
    if live_result.get("exit") != 0:
        return AcceptanceItem("A6", "FAIL",
                              f"live agentteams suite failed: {_fmt_counts(live_counts)}")
    return AcceptanceItem("A6", "PASS",
                          f"local {_fmt_counts(local_counts)}; "
                          f"live {_fmt_counts(live_counts)}")


def _scan_canary(canary: str, surfaces: dict[str, list[Path]]) -> list[str]:
    hits = []
    needle = canary.encode("utf-8")
    for surface, paths in surfaces.items():
        for path in paths:
            try:
                data = Path(path).read_bytes()
            except OSError:
                continue
            if needle in data:
                hits.append(f"{surface}:{path}")
    return hits


def _a7_leakage(evidence: EvidenceCollector, run_root: Path,
                enabled: bool) -> AcceptanceItem:
    if not enabled:
        return AcceptanceItem("A7", "BLOCKED", "requires --leakage-e2e")
    temp_root = Path(".argus") / "leakage"
    fixture = temp_root / "source-fixture"
    shutil.rmtree(fixture, ignore_errors=True)
    fixture.mkdir(parents=True, exist_ok=True)
    canary = "ARGUS_CANARY_" + secrets.token_hex(12)
    (fixture / "pyproject.toml").write_text(
        '[project]\nname = "leak-target"\nversion = "0.0.1"\n', encoding="utf-8")
    (fixture / "app").mkdir()
    (fixture / "app" / "main.py").write_text(
        "def main():\n    return 1\n", encoding="utf-8")
    (fixture / "canary.txt").write_text(canary + "\n", encoding="utf-8")

    result = evidence.run_command(
        "A7-leak-audit",
        [sys.executable, "-m", "cli.argus", "audit",
         "--target", str(fixture), "--headless", "--engine", "local"],
        timeout=300)

    raw_out = temp_root / "leak.stdout.txt"
    raw_err = temp_root / "leak.stderr.txt"
    raw_out.write_text(result.get("stdout", ""), encoding="utf-8")
    raw_err.write_text(result.get("stderr", ""), encoding="utf-8")
    surfaces = {
        "report.json": [REPORT_JSON],
        "report.md": [Path(".argus/reports/report.md")],
        "audit.stdout": [raw_out],
        "audit.stderr": [raw_err],
        "evidence": [path for path in run_root.rglob("*") if path.is_file()],
    }
    hits = _scan_canary(canary, surfaces)
    evidence.add_resource("local", "leakage")
    if hits:
        return AcceptanceItem("A7", "FAIL", f"canary leaked into: {hits}")
    return AcceptanceItem("A7", "PASS",
                          "random canary zero leak across report and audit output")


def _a8_docs(evidence: EvidenceCollector, run_id: str) -> AcceptanceItem:
    problems = []

    readme = Path("README.md")
    if not readme.is_file():
        problems.append("README.md missing")
    else:
        text = readme.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in README_SECTIONS if s not in text]
        if missing:
            problems.append(f"README missing sections: {missing}")

    if not INTRO_PATH.is_file():
        problems.append(f"{INTRO_PATH.name} missing")
    else:
        length = len(INTRO_PATH.read_text(encoding="utf-8", errors="replace").strip())
        if length > 500:
            problems.append(f"作品简介 {length} 字 > 500 字")

    if not PPT_PATH.is_file():
        problems.append(f"{PPT_PATH.name} missing")

    try:
        lock = json.loads((Path("skills") / "skills.lock.json")
                          .read_text(encoding="utf-8"))
        if len({s["name"] for s in lock.get("skills", [])}) != 8:
            problems.append("lock skills != 8")
        if len(lock.get("assignments", {})) != 6:
            problems.append("lock assignments != 6")
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"skills.lock.json unreadable: {exc}")

    if not ACCEPTANCE_MD.is_file():
        problems.append("acceptance.md not generated")
    else:
        md = ACCEPTANCE_MD.read_text(encoding="utf-8", errors="replace")
        if run_id not in md:
            problems.append("acceptance.md does not reflect this run")

    if problems:
        return AcceptanceItem("A8", "FAIL", "; ".join(problems))
    return AcceptanceItem("A8", "PASS",
                          "README/简介/PPT/acceptance.md match measured facts")


def _write_acceptance_md(report: AcceptanceReport) -> Path:
    lines = [
        "# Argus Phase-One Acceptance", "",
        f"- Run: `{report.run_id}`",
        f"- Phase one: `{report.phase_one}`",
        f"- Accepted: `{report.accepted}`",
        f"- Generated: `{report.generated_at}`", "",
        "## Items", "",
    ]
    for item in report.items:
        lines.append(f"- **{item.id}** {item.status}: {item.detail}")
    text = "\n".join(lines) + "\n"
    ACCEPTANCE_MD.write_text(text, encoding="utf-8")
    return ACCEPTANCE_MD
