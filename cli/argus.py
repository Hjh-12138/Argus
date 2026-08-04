"""Argus v2 headless CLI。

核心闭环：AuditRequest -> preflight -> snapshot -> schedule -> assessors -> Meta ->
Synth/policy -> atomic reports + stable exit code。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.code.detector import CodeDetector
from agents.delivery.detector import DeliveryDetector
from agents.dep.detector import DepDetector
from agents.dep.tools import load_registry_fixture
from agents.sec.detector import SecDetector
from agents.synth.tools import synthesize
from core.config import ConfigValidationError, effective_config_summary, load_config
from core.meta import MetaReviewer
from core.preflight import preflight
from core.report import ReportWriteError, write_report
from core.scheduler import Change, heuristic_schedule
from core.schemas import AgentResult, Evidence, Finding
from core.snapshot import SnapshotBuilder
from core.state import INVALID_TRANSITION, StateStore

EXIT = {"pass": 0, "warn": 1, "block": 2, "unknown": 3}
SYSTEM_ERROR = 4
CANCELLED = 130
IMPLEMENTED_ASSESSORS = {"dep", "code", "sec", "delivery"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argus")
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit = sub.add_parser("audit", help="Run an audit")
    audit.add_argument("--target", required=True)
    audit.add_argument("--base")
    audit.add_argument("--head")
    audit.add_argument("--headless", action="store_true")
    audit.add_argument("--block-on")
    audit.add_argument("--registry-fixture")
    audit.add_argument("--engine", choices=["agentteams", "local"],
                       default="agentteams",
                       help="Execution engine for headless audits (default: agentteams)")
    audit.add_argument("--workspace-mode", choices=["current-source", "plain"],
                       default="plain")
    audit.add_argument("--acceptance-probe", choices=["hallucination-revision"],
                       default=None, help=argparse.SUPPRESS)
    audit.add_argument("--demo-invalid-finding", action="store_true",
                       help=argparse.SUPPRESS)

    pf = sub.add_parser("preflight", help="Validate target and environment")
    pf.add_argument("--target", required=True)

    acceptance = sub.add_parser("acceptance", help="Phase-one acceptance commands")
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_cmd", required=True)
    phase_one = acceptance_sub.add_parser("phase-one", help="Run A1-A8 acceptance")
    phase_one.add_argument("--target", required=True)
    phase_one.add_argument("--workspace-mode", default="current-source")
    phase_one.add_argument("--agentteams-live", action="store_true")
    phase_one.add_argument("--acceptance-probe", default="hallucination-revision")
    phase_one.add_argument("--leakage-e2e", action="store_true")
    cleanup = acceptance_sub.add_parser("cleanup", help="Exact-manifest cleanup")
    cleanup.add_argument("--run-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "preflight":
            return _cmd_preflight(args)
        if args.cmd == "acceptance":
            return _cmd_acceptance(args)
        return _cmd_audit(args)
    except KeyboardInterrupt:
        print("[argus] cancelled", file=sys.stderr)
        return CANCELLED
    except (ConfigValidationError, ReportWriteError, INVALID_TRANSITION) as exc:
        print(f"[argus] system error: {exc}", file=sys.stderr)
        return SYSTEM_ERROR


def _cmd_preflight(args) -> int:
    cfg = load_config([], Path.cwd())
    result = preflight(Path(args.target), cfg)
    print(json.dumps({
        "ok": result.ok,
        "canonical_root": str(result.canonical_root),
        "manifest": result.manifest,
        "language": result.language,
        "file_count": result.file_count,
        "size_bytes": result.size_bytes,
        "unsafe_links": result.unsafe_links,
    }, ensure_ascii=False, indent=2))
    return 0 if result.ok else SYSTEM_ERROR


def _begin_audit(store, run_id: str, target: Path, cfg) -> object | None:
    """CREATED -> PREFLIGHT prefix shared by the local and AgentTeams engines.

    The AgentTeams engine must not jump straight to SNAPSHOTTING: the run
    state machine only allows CREATED -> PREFLIGHT first. Returns the
    preflight result, or None after recording a FAILED transition when the
    target contains unsafe symlinks.
    """
    store.transition(run_id, "CREATED", "PREFLIGHT")
    pf = preflight(target, cfg)
    if pf.unsafe_links:
        store.transition(run_id, "PREFLIGHT", "FAILED")
        print(f"[argus] unsafe symlink(s): {pf.unsafe_links}", file=sys.stderr)
        return None
    return pf


def _cmd_audit(args) -> int:
    cli_overrides: list[str] = []
    if args.block_on:
        cli_overrides.extend(["--block-on", args.block_on])
    cfg = load_config(cli_overrides, Path.cwd())
    print(f"[argus] config={effective_config_summary(cfg)}")

    target = Path(args.target)
    store = StateStore(Path(".argus/state.db"))
    run_id = store.begin_run()

    if args.headless and args.engine == "agentteams":
        return _audit_agentteams(args, cfg, store, run_id, target)

    try:
        if _begin_audit(store, run_id, target, cfg) is None:
            return SYSTEM_ERROR
        store.transition(run_id, "PREFLIGHT", "SNAPSHOTTING")
        snapshot, coverage = SnapshotBuilder().build(target)
        store.save_run(run_id, snapshot_id=snapshot.snapshot_id,
                       base_revision=args.base, head_revision=args.head)

        store.transition(run_id, "SNAPSHOTTING", "SCHEDULED")
        changes = [_change_from_file(f) for f in snapshot.files]
        schedule = heuristic_schedule(changes)
        if schedule.intentional_skip:
            selected = set()
        else:
            selected = schedule.agents & IMPLEMENTED_ASSESSORS
            # 初赛全量核心链路：manifest/CI/code 必须覆盖 dep/code/sec/delivery。
            selected |= _required_for_snapshot(snapshot)
        print(f"[argus] schedule={','.join(sorted(selected)) or 'intentional-skip'}")

        store.transition(run_id, "SCHEDULED", "RUNNING")
        registry = _load_registry(args.registry_fixture)
        results = list(_run_assessors(snapshot, selected, registry))
        if args.demo_invalid_finding:
            _inject_demo_hallucination(snapshot, results)

        store.transition(run_id, "RUNNING", "META_REVIEW")
        decisions = MetaReviewer().review(snapshot, tuple(results))
        for decision in decisions:
            if decision.label == "HALLUCINATION":
                print(f"[argus] meta rejected {decision.finding_id}: "
                      f"{','.join(decision.reason_codes)}")

        store.transition(run_id, "META_REVIEW", "SYNTHESIZING")
        expected_required = {r.agent for r in results if r.required}
        policy, report_data = synthesize(
            run_id, snapshot, tuple(results), decisions, cfg, coverage)
        # 若 schedule 需要已实现的 required Agent 但 result 缺失，重算 unknown。
        completed = {r.agent for r in results if r.status == "completed"}
        if expected_required - completed:
            from core.policy import evaluate_policy
            from core.report import render_report
            policy = evaluate_policy(decisions, results, cfg,
                                     expected_required=expected_required)
            report_data = render_report(run_id, snapshot, tuple(results), decisions,
                                        policy, coverage=coverage)

        json_path, md_path = write_report(cfg.output.directory, report_data)
        store.save_run(run_id, gate=policy.release_gate)
        store.transition(run_id, "SYNTHESIZING", "COMPLETED")
        print(f"[argus] gate={policy.release_gate}")
        for reason in policy.reasons:
            print(f"[argus] reason={reason}")
        print(f"[argus] report={json_path}")
        print(f"[argus] report={md_path}")
        return _exit_for_gate(policy.release_gate, cfg.policy.incomplete_run)
    except SystemExit:
        if store.get_status(run_id) == "PREFLIGHT":
            store.transition(run_id, "PREFLIGHT", "FAILED")
        raise
    except Exception as exc:
        current = store.get_status(run_id)
        if (current, "FAILED") in __import__("core.state", fromlist=["VALID_TRANSITIONS"]).VALID_TRANSITIONS:
            store.transition(run_id, current, "FAILED")
        print(f"[argus] audit failed in {current}: {exc}", file=sys.stderr)
        return SYSTEM_ERROR
    finally:
        store.close()


def _audit_agentteams(args, cfg, store, run_id: int, target: Path) -> int:
    """Formal headless audit on real AgentTeams Workers and typed Tasks."""
    from core.workspace_snapshot import WorkspaceSnapshotBuilder
    from agentteams.hiclaw_client import HiclawClient
    from agentteams.project_driver import ProjectDriver
    from agentteams.worker_payloads import SnapshotReference

    if _begin_audit(store, run_id, target, cfg) is None:
        return SYSTEM_ERROR
    store.transition(run_id, "PREFLIGHT", "SNAPSHOTTING")
    archive = Path(".argus") / "snapshots" / f"{run_id}.zip"
    bundle = WorkspaceSnapshotBuilder().build(target, archive)
    snapshot_ref = SnapshotReference(
        snapshot_id=bundle.snapshot.snapshot_id,
        source_root="/root/hiclaw-fs/shared",
        files=[
            {"path": f.path, "sha256": f.sha256, "size": f.size,
             "language": f.language} for f in bundle.snapshot.files
        ],
        archive_sha256=bundle.archive_sha256,
    )

    store.transition(run_id, "SNAPSHOTTING", "SCHEDULED")
    store.transition(run_id, "SCHEDULED", "RUNNING")
    client = HiclawClient()
    driver = ProjectDriver(client, Path.cwd())
    request = {"project_id": f"argus-run-{run_id}", "run_id": f"run-{run_id}"}
    outcome = driver.run(request, snapshot_ref,
                         profile="phase-one-acceptance",
                         acceptance_probe=None)
    store.save_run(run_id, gate=outcome.gate)
    print(f"[argus] project={outcome.project_id} status={outcome.status} "
          f"gate={outcome.gate}")
    if outcome.status != "completed":
        store.transition(run_id, "RUNNING", "PARTIAL")
        return SYSTEM_ERROR
    for path in outcome.report_paths:
        print(f"[argus] report={path}")
    store.transition(run_id, "RUNNING", "META_REVIEW")
    store.transition(run_id, "META_REVIEW", "SYNTHESIZING")
    store.transition(run_id, "SYNTHESIZING", "COMPLETED")
    return EXIT.get(outcome.gate, EXIT["unknown"])


def _cmd_acceptance(args) -> int:
    if args.acceptance_cmd == "phase-one":
        from acceptance.phase_one import run_phase_one
        report = run_phase_one(
            target=Path(args.target),
            workspace_mode=args.workspace_mode,
            agentteams_live=args.agentteams_live,
            acceptance_probe=args.acceptance_probe,
            leakage_e2e=args.leakage_e2e,
        )
        print(f"[argus] phase_one={report.phase_one} accepted={report.accepted}")
        return 0 if report.accepted else SYSTEM_ERROR
    if args.acceptance_cmd == "cleanup":
        from acceptance.cleanup import run_cleanup
        removed = run_cleanup(args.run_id)
        print(f"[argus] cleanup removed {len(removed)} resources")
        return 0
    return SYSTEM_ERROR


def _change_from_file(sf) -> Change:
    ext = Path(sf.path).suffix.lower()
    doc = ext in (".md", ".rst", ".txt")
    route = any(token in sf.path.lower() for token in
                ("route", "search", "query", "auth", "middleware"))
    return Change(path=sf.path, status="modified",
                  is_comment_or_doc_only=doc, contains_route_or_query=route)


def _required_for_snapshot(snapshot) -> set[str]:
    paths = {f.path.lower() for f in snapshot.files}
    required = {"code"} if any(Path(p).suffix in
                                (".py", ".js", ".ts", ".tsx", ".go", ".java")
                                for p in paths) else set()
    if any(Path(p).name in ("pyproject.toml", "requirements.txt", "package.json", "go.mod")
           for p in paths):
        required.add("dep")
    if any(p.startswith(".github/workflows/") or p == ".gitlab-ci.yml" for p in paths):
        required.add("delivery")
    if any(any(token in p for token in ("search", "query", "auth", ".env")) for p in paths):
        required.add("sec")
    return required


def _run_assessors(snapshot, selected: set[str], registry: dict) -> tuple[AgentResult, ...]:
    detectors = {
        "dep": lambda: DepDetector().detect(snapshot, registry),
        "code": lambda: CodeDetector().detect(snapshot),
        "sec": lambda: SecDetector().detect(snapshot),
        "delivery": lambda: DeliveryDetector().detect(snapshot),
    }
    out: list[AgentResult] = []
    for agent in sorted(selected):
        try:
            findings = detectors[agent]()
            out.append(_agent_result(agent, snapshot.snapshot_id, "completed", findings))
        except Exception as exc:
            out.append(_agent_result(agent, snapshot.snapshot_id, "failed", (),
                                     error_code="AGENT_FAILED",
                                     error_message=str(exc)[:500]))
    return tuple(out)


def _agent_result(agent, snapshot_id, status, findings, error_code=None,
                  error_message=None) -> AgentResult:
    return AgentResult(
        agent=agent,
        agent_version_id=f"{agent}-2026.08.02.1",
        status=status,
        required=True,
        findings=tuple(findings),
        input_snapshot_id=snapshot_id,
        rule_set_version="2026.08.02",
        prompt_version=None,
        model_version=None,
        dataset_version="initial",
        error_code=error_code,
        error_message=error_message,
        metrics={"files_scanned": None},
    )


def _load_registry(explicit: str | None) -> dict:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path("demo/scenarios/ai-pr-three-defects/registry-fixture.json"))
    for path in candidates:
        if path.exists():
            return load_registry_fixture(path)
    return {}


def _inject_demo_hallucination(snapshot, results: list[AgentResult]):
    """仅 Demo profile：注入引用不存在路径的 finding，证明 Meta 会拦截。"""
    fake = Finding(
        id="demo-hallucination-config-88", agent="code",
        category="code.contract_violation", severity="medium", confidence=0.9,
        title="Deliberately invalid demo finding", detail="demo-only invalid reference",
        file="app/config.py", line_start=88, line_end=88,
        remediation="demo-only", verification="demo-only", rollback=None, cwe=None,
        fingerprint="demo-invalid-fingerprint", rule_id="DEMO-INVALID", rule_version="1",
        evidence=Evidence(context_lines=("nonexistent",), source_sha256="0" * 64,
                          redacted_value=None, detector="demo.invalid-finding",
                          reasoning_summary=None),
    )
    for index, result in enumerate(results):
        if result.agent == "code":
            data = result.__dict__.copy()
            data["findings"] = result.findings + (fake,)
            results[index] = AgentResult(**data)
            return
    results.append(_agent_result("code", snapshot.snapshot_id, "completed", (fake,)))


def _exit_for_gate(gate: str, incomplete_policy: str) -> int:
    if gate != "unknown":
        return EXIT[gate]
    if incomplete_policy == "block":
        return EXIT["block"]
    if incomplete_policy == "warn":
        return EXIT["warn"]
    return EXIT["unknown"]


if __name__ == "__main__":
    raise SystemExit(main())
