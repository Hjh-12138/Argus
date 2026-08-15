"""Argus v2 评测 harness（R5.1）。

读 manifest -> 每个场景跑 N 次 audit -> 按语义键 (agent, category, file, line_start)
对齐 ground truth -> 算 recall / precision / gate 一致性。

判据独立于 Argus 输出（P5）：ground-truth.json 由人标注缺陷语义，语义键不依赖
detector 生成的 id/fingerprint。harness 只做对齐与统计，不解释缺陷语义。

每次 audit 在隔离临时目录里跑（cwd=临时目录、PYTHONPATH=项目根），避免污染
项目根的 .argus/state.db 与 reports。默认 --engine local（确定性引擎）；
--engine agentteams 走 Manager LLM 路径（非确定性，需 AgentTeams 环境）。

用法（项目根目录）:
    python demo/eval/harness.py                          # 全量 3 次
    python demo/eval/harness.py --runs 1 --only complex-webapp
    python demo/eval/harness.py --engine agentteams --runs 5
    python demo/eval/harness.py --strict --json-out demo/eval/last-run.json

退出码:
    0  所有场景无审计错误（默认；质量缺口只报告不判失败）
    1  有审计错误（subprocess 失败 / report 缺失 / report 不可解析），或 --strict
       下任一场景未完全命中（gate 不一致 / recall<1 / precision<1）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

EVAL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_ROOT.parent.parent

MANIFEST_NAME = "manifest.json"
GROUND_TRUTH_NAME = "ground-truth.json"
SRC_DIR_NAME = "src"
FIXTURE_NAME = "registry-fixture.json"
REPORT_REL = Path(".argus") / "reports" / "report.json"

ALLOWED_GATES = ("pass", "warn", "block", "unknown")


# ---------------------------------------------------------------------------
# 场景发现 / ground truth 加载
# ---------------------------------------------------------------------------

def load_manifest(eval_root: Path = EVAL_ROOT) -> list[dict[str, str]]:
    """读 manifest.json；校验每个场景的 ground truth 与 src 目录存在。"""
    manifest_path = eval_root / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenarios = list(data.get("scenarios", []))
    for entry in scenarios:
        base = eval_root / entry["path"]
        if not (base / GROUND_TRUTH_NAME).exists():
            raise FileNotFoundError(
                f"scenario missing {GROUND_TRUTH_NAME}: {entry.get('id')} at {base}")
        if not (base / SRC_DIR_NAME).is_dir():
            raise FileNotFoundError(
                f"scenario missing src/ dir: {entry.get('id')} at {base / SRC_DIR_NAME}")
    return scenarios


def load_ground_truth(scenario_path: Path) -> dict[str, Any]:
    gt = json.loads((scenario_path / GROUND_TRUTH_NAME).read_text(encoding="utf-8"))
    gate = gt.get("expected_gate")
    if gate not in ALLOWED_GATES:
        raise ValueError(
            f"{scenario_path.name}: invalid expected_gate {gate!r} "
            f"(must be one of {ALLOWED_GATES})")
    return gt


# ---------------------------------------------------------------------------
# audit 执行（隔离子进程）
# ---------------------------------------------------------------------------

def run_audit(scenario_path: Path, engine: str, python: str | None = None,
              timeout_s: int = 300) -> dict[str, Any]:
    """在隔离临时目录跑一次 audit，返回 report dict 或 error dict。

    error dict 形如 {"ok": False, "error": ..., "stdout": ..., "stderr": ...}。
    report dict 形如 {"ok": True, "report": ..., "exit_code": ...}。
    """
    src = scenario_path / SRC_DIR_NAME
    fixture = scenario_path / FIXTURE_NAME
    python = python or sys.executable

    with tempfile.TemporaryDirectory(prefix="argus-eval-") as tmp:
        scratch = Path(tmp)
        cmd = [python, "-m", "cli.argus", "audit",
               "--target", str(src), "--engine", engine, "--headless"]
        if fixture.exists():
            cmd += ["--registry-fixture", str(fixture)]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        try:
            proc = subprocess.run(cmd, cwd=str(scratch), env=env,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            return {"ok": False,
                    "error": f"timeout after {timeout_s}s",
                    "stdout": "", "stderr": str(exc)[:500]}
        except OSError as exc:
            return {"ok": False, "error": f"subprocess launch failed: {exc}",
                    "stdout": "", "stderr": ""}

        report_path = scratch / REPORT_REL
        if not report_path.exists():
            return {"ok": False, "error": "report.json not written",
                    "stdout": (proc.stdout or "")[-2000:],
                    "stderr": (proc.stderr or "")[-2000:],
                    "exit_code": proc.returncode}
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"report unparseable: {exc}",
                    "stdout": (proc.stdout or "")[-2000:],
                    "stderr": (proc.stderr or "")[-2000:],
                    "exit_code": proc.returncode}
        return {"ok": True, "report": report, "exit_code": proc.returncode,
                "stdout": proc.stdout or "", "stderr": proc.stderr or ""}


# ---------------------------------------------------------------------------
# 语义键对齐与统计
# ---------------------------------------------------------------------------

def semantic_key(finding: dict[str, Any]) -> tuple:
    """语义键 (agent, category, file, line_start)，与 ground truth 对齐。

    不用 detector 生成的 id/fingerprint —— 那是实现细节，用于判据等于让
    detector 给自己出题（P5）。
    """
    file_ = finding.get("file") or ""
    line = finding.get("line_start")
    return (str(finding.get("agent") or ""),
            str(finding.get("category") or ""),
            str(file_),
            int(line) if isinstance(line, int) else None)


def ground_truth_keys(gt: dict[str, Any]) -> dict[tuple, dict]:
    return {semantic_key(f): f for f in gt.get("expected_findings", [])}


def _safe_key(key: tuple) -> tuple:
    return (key[0], key[1], key[2], str(key[3]))


def evaluate_reports(runs: list[dict[str, Any]], gt: dict[str, Any]) -> dict[str, Any]:
    """对 N 次 audit 结果做对齐统计。

    召回（recall）：ground truth 里的每个 finding 是否被至少一次 run 找到。
    精确（precision）：Argus 报告的每个 finding（跨 run 按语义键去重）是否在
    ground truth 里。同一 finding 在多次 run 重复报告不重复计 FP。
    gate 一致性：全部 N 次 run 的 release_gate 都等于 expected_gate；有 run
    出错即视为不一致（fail-closed，错误不算 pass）。
    """
    expected_gate = gt.get("expected_gate")
    gt_by_key = ground_truth_keys(gt)

    seen: set = set()
    argus_keys: list[tuple] = []
    for run in runs:
        if not run.get("ok"):
            continue
        for f in run["report"].get("findings", []):
            key = semantic_key(f)
            if key not in seen:
                seen.add(key)
                argus_keys.append(key)

    argus_set = set(argus_keys)
    matched = {k: v for k, v in gt_by_key.items() if k in argus_set}
    missing = {k: v for k, v in gt_by_key.items() if k not in argus_set}
    fp_keys = [k for k in argus_keys if k not in gt_by_key]

    tp = len(matched)
    total_gt = len(gt_by_key)
    total_reported = tp + len(fp_keys)
    recall = tp / total_gt if total_gt else 1.0
    precision = tp / total_reported if total_reported else 1.0
    f1 = (2 * recall * precision / (recall + precision)
          if (recall + precision) else 0.0)

    gates: list[str] = []
    errors: list[str] = []
    for run in runs:
        if not run.get("ok"):
            errors.append(str(run.get("error", "unknown")))
            continue
        gates.append(str(run["report"].get("release_gate")))
    dist: dict[str, int] = {}
    for g in gates:
        dist[g] = dist.get(g, 0) + 1

    gate_consistent = (not errors and bool(gates)
                       and all(g == expected_gate for g in gates))
    full_match = (gate_consistent and recall == 1.0 and precision == 1.0)

    return {
        "scenario_id": gt.get("scenario_id"),
        "title": gt.get("title", ""),
        "category": gt.get("category", ""),
        "expected_gate": expected_gate,
        "runs": len(runs),
        "errors": errors,
        "gate_distribution": dist,
        "gate_consistent": gate_consistent,
        "full_match": full_match,
        "argus_findings": argus_keys,
        "matched_gt_keys": sorted(matched.keys(), key=_safe_key),
        "missing_gt_keys": sorted(missing.keys(), key=_safe_key),
        "false_positive_keys": fp_keys,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def _sample_tokens(token_captor: Callable | None):
    """采样一次网关 token 总数。返回 (value|None, error|None)。"""
    if token_captor is None:
        return None, None
    try:
        return token_captor(), None
    except Exception as exc:
        return None, str(exc)[:200]


def _token_capture(before, after) -> dict:
    """累计计数器差分 → 场景级 token 成本。"""
    return {
        "input_delta": max(0, int(after.input_tokens) - int(before.input_tokens)),
        "output_delta": max(0, int(after.output_tokens) - int(before.output_tokens)),
        "total_delta": max(0, int(after.total_tokens) - int(before.total_tokens)),
    }


def run_scenario(eval_root: Path, entry: dict[str, str], runs: int,
                 engine: str, python: str | None, timeout_s: int,
                 token_captor: Callable | None = None) -> dict[str, Any]:
    """跑一个场景。token_captor 启用时对网关 token 计数做前后差分记入 `tokens`。"""
    scenario_path = eval_root / entry["path"]
    gt = load_ground_truth(scenario_path)
    before, before_err = _sample_tokens(token_captor)
    attempts = [run_audit(scenario_path, engine, python, timeout_s)
                for _ in range(runs)]
    result = evaluate_reports(attempts, gt)
    if token_captor is None:
        result["tokens"] = None
    elif before_err is not None:
        result["tokens"] = {"error": before_err}
    else:
        after, after_err = _sample_tokens(token_captor)
        if after_err is not None:
            result["tokens"] = {"error": after_err}
        else:
            result["tokens"] = _token_capture(before, after)
    return result


# ---------------------------------------------------------------------------
# 展示 / 汇总
# ---------------------------------------------------------------------------

def render_result(result: dict[str, Any]) -> str:
    verdict = "MATCH" if result["full_match"] else "DIFF"
    dist = result["gate_distribution"]
    got = ("+".join(f"{k}:{v}" for k, v in sorted(dist.items()))
           or "audit-error")
    missing = ",".join(_safe_key(k)[2] + ":" + _safe_key(k)[3]
                       for k in result["missing_gt_keys"]) or "-"
    tokens = result.get("tokens")
    if isinstance(tokens, dict) and "total_delta" in tokens:
        token_str = f" tokens={tokens['total_delta']:,}"
    elif isinstance(tokens, dict) and "error" in tokens:
        token_str = " tokens=ERR"
    else:
        token_str = ""
    return (f"{verdict:5}  {result['scenario_id']:<32} "
            f"expected={result['expected_gate']:<6} got={got:<12} "
            f"recall={result['recall']:.2f} precision={result['precision']:.2f} "
            f"fp={len(result['false_positive_keys'])} missing={missing}"
            f"{token_str}")


def build_report(results: list[dict[str, Any]], argv: list[str]) -> dict[str, Any]:
    n = len(results)
    full = sum(1 for r in results if r["full_match"])
    gate_ok = sum(1 for r in results if r["gate_consistent"])
    with_errors = sum(1 for r in results if r["errors"])
    recall_macro = (sum(r["recall"] for r in results) / n) if n else 1.0
    precision_macro = (sum(r["precision"] for r in results) / n) if n else 1.0
    return {
        "schema_version": "1",
        "argv": argv,
        "summary": {
            "scenarios": n,
            "full_match": full,
            "gate_consistent": gate_ok,
            "with_audit_errors": with_errors,
            "recall_macro": recall_macro,
            "precision_macro": precision_macro,
        },
        "scenarios": results,
    }


def collect_results(eval_root: Path, scenarios: list[dict[str, str]], runs: int,
                    engine: str, python: str, timeout_s: int,
                    token_captor: Callable | None = None) -> list[dict[str, Any]]:
    """跑全部场景，返回 results 列表。审计/解析异常按 fail-closed 兜底为 error 场景。"""
    results: list[dict[str, Any]] = []
    for entry in scenarios:
        try:
            result = run_scenario(eval_root, entry, runs, engine, python, timeout_s,
                                  token_captor=token_captor)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            result = {
                "scenario_id": entry.get("id"),
                "title": entry.get("path"),
                "category": entry.get("category"),
                "expected_gate": None,
                "runs": runs,
                "errors": [str(exc)],
                "gate_distribution": {},
                "gate_consistent": False,
                "full_match": False,
                "argus_findings": [],
                "matched_gt_keys": [],
                "missing_gt_keys": [],
                "false_positive_keys": [],
                "recall": 0.0, "precision": 0.0, "f1": 0.0,
                "tokens": None,
            }
        results.append(result)
    return results


def run_evaluation(eval_root: Path, scenarios: list[dict[str, str]], runs: int,
                   engine: str, python: str, timeout_s: int,
                   token_captor: Callable | None = None,
                   argv: list[str] | None = None) -> dict[str, Any]:
    """R5.2 gate 复用入口：跑评测并返回完整报告 dict（== harness --json-out 的产物）。"""
    results = collect_results(eval_root, scenarios, runs, engine, python, timeout_s,
                              token_captor=token_captor)
    return build_report(results, list(argv or []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="argus-eval", description="Argus v2 评测 harness（R5.1）")
    parser.add_argument("--eval-root", default=str(EVAL_ROOT),
                        help="评测集根目录（含 manifest.json）")
    parser.add_argument("--runs", type=int, default=3,
                        help="每个场景的 audit 次数（默认 3）")
    parser.add_argument("--engine", choices=["local", "agentteams"],
                        default="local",
                        help="执行引擎（默认 local；agentteams 非确定性需环境）")
    parser.add_argument("--only", default="",
                        help="逗号分隔的 scenario_id 过滤（默认全部）")
    parser.add_argument("--python", default="",
                        help="Python 解释器路径（默认 sys.executable）")
    parser.add_argument("--timeout", type=int, default=300,
                        help="单次 audit 超时秒数（默认 300）")
    parser.add_argument("--json-out", default="",
                        help="把完整结果写入 JSON 文件（R5.2 版本 pin 用）")
    parser.add_argument("--strict", action="store_true",
                        help="任一场景未完全命中即退出码 1")
    parser.add_argument("--token-cost", action="store_true",
                        help="对 agentteams 场景记录 AI 网关 token 差分成本（需网关可达）")
    parser.add_argument("--gateway-container", default="",
                        help="docker exec 取网关指标（宿主机用，如 agentteams-controller）")
    parser.add_argument("--gateway-endpoint", default="",
                        help="网关 Prometheus 端点（容器内直连，默认 "
                             "http://agentteams-controller:15020/stats/prometheus）")
    args = parser.parse_args(argv)

    eval_root = Path(args.eval_root)
    scenarios = load_manifest(eval_root)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        scenarios = [s for s in scenarios if s.get("id") in wanted]
    if not scenarios:
        print(f"[argus-eval] no scenarios matched (--only={args.only!r})",
              file=sys.stderr)
        return 1

    python = args.python or sys.executable
    token_captor = None
    if args.token_cost:
        from agentteams.gateway_metrics import fetch_token_totals
        token_captor = lambda: fetch_token_totals(
            args.gateway_container, args.gateway_endpoint)
    results = collect_results(eval_root, scenarios, args.runs,
                              args.engine, python, args.timeout,
                              token_captor=token_captor)

    print(f"[argus-eval] engine={args.engine} runs={args.runs} "
          f"scenarios={len(scenarios)}")
    for result in results:
        print(render_result(result))

    report = build_report(results, list(argv or []))
    summary = report["summary"]
    print(f"[argus-eval] SUMMARY full_match={summary['full_match']}/"
          f"{summary['scenarios']} gate_consistent={summary['gate_consistent']}/"
          f"{summary['scenarios']} audit_errors={summary['with_audit_errors']} "
          f"recall_macro={summary['recall_macro']:.2f} "
          f"precision_macro={summary['precision_macro']:.2f}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[argus-eval] json={out}")

    infra_error = summary["with_audit_errors"] > 0
    if args.strict and summary["full_match"] < summary["scenarios"]:
        return 1
    return 1 if infra_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
