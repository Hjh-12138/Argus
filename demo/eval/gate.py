"""Argus v2 评测门禁（R5.2）。

流程：变更 -> 跑评测 -> 与 `eval.lock.json` 里 pin 的基线对比 -> 达阈值才升版本。
复用 `contract.lock.json` / `skills.lock.json` 的 pin 机制：lock 文件记录版本
指纹 + 已验证基线 + 权重，门禁按「不回归」判据拒绝不合格变更。

判据独立于 Argus（P5）：基线来自 ground-truth 对齐后的指标，不含 Meta 判断。
评测集内容（manifest + ground-truth）计入 eval 指纹——ground truth 一改就是
测量基准变了，门禁应拒绝并提示重 pin，而非拿旧基线硬比。

用法（项目根目录）:
    python demo/eval/gate.py --pin            # 无 pin 时建立基线；门禁通过后推进 pin
    python demo/eval/gate.py                  # 对现有 pin 跑门禁（默认，不写文件）
    python demo/eval/gate.py --json cur.json  # 消费 harness --json-out 的结果，不重跑
    python demo/eval/gate.py --pin --force    # 门禁未过仍强制推进（显式知情）

退出码:
    0  通过（且 --pin 时已推进 pin）
    1  未通过（回归 / 未达阈值 / 审计错误 / 评测集变更需重 pin）
    2  无 pin 且未 --pin（需先 --pin 建立基线）
    3  输入/配置错误（--json / pin 文件损坏）
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness import (EVAL_ROOT, PROJECT_ROOT, GROUND_TRUTH_NAME,
                     MANIFEST_NAME, load_manifest, render_result, run_evaluation)

PIN_NAME = "eval.lock.json"
DEFAULT_WEIGHTS = {"recall": 1.0, "precision": 1.0, "gate": 1.0}
_EPS = 1e-6

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NO_PIN = 2
EXIT_CONFIG = 3


# ---------------------------------------------------------------------------
# 版本指纹（复用 skills.lock.json 的 content-digest pin 思路）
# ---------------------------------------------------------------------------

def git_short_sha(project_root: Path = PROJECT_ROOT) -> str:
    """短 commit SHA；非 git 环境 fallback 为 'unknown'。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _paths_fingerprint(files: list[Path], base: Path) -> str:
    """内容摘要：排序后的相对路径 + 字节。跳过 __pycache__/.pyc 与 dot 目录
    （对齐 hiclaw_client.skill_directory_digest 风格；dot 目录里可能是 eval 集
    的副本/临时产物，不算测量基准）。"""
    digest = hashlib.sha256()
    for path in sorted(files):
        rel = path.relative_to(base)
        if (any(part.startswith(".") for part in rel.parts)
                or "__pycache__" in rel.parts or rel.suffix == ".pyc"):
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def engine_fingerprint(project_root: Path = PROJECT_ROOT) -> str:
    """审计引擎源码摘要：core/agents/cli/agentteams。"""
    files: list[Path] = []
    for directory in ("core", "agents", "cli", "agentteams"):
        root = project_root / directory
        for path in root.rglob("*"):
            if (path.is_file() and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"):
                files.append(path)
    return _paths_fingerprint(files, project_root)


def eval_fingerprint(eval_root: Path = EVAL_ROOT) -> str:
    """评测集内容摘要：manifest + 全部 ground-truth.json。测量基准变了门禁应拒绝。"""
    files: list[Path] = []
    manifest = eval_root / MANIFEST_NAME
    if manifest.exists():
        files.append(manifest)
    files.extend(p for p in eval_root.rglob(GROUND_TRUTH_NAME) if p.is_file())
    return _paths_fingerprint(files, eval_root)


# ---------------------------------------------------------------------------
# 门禁判据
# ---------------------------------------------------------------------------

@dataclass
class GateVerdict:
    accepted: bool
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    score_base: float = 0.0
    score_cur: float = 0.0
    cost_base: int | None = None
    cost_cur: int | None = None
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def gate_score(report: dict[str, Any], weights: dict[str, float] | None = None) -> float:
    """D3 加权复合分：w_r*recall_macro + w_p*precision_macro + w_g*gate_ratio。
    默认 1/1/1 = 无加权；调权允许跨场景权衡。"""
    w = dict(weights or DEFAULT_WEIGHTS)
    s = report.get("summary", {})
    n = s.get("scenarios", 0)
    gate_ratio = s.get("gate_consistent", 0) / n if n else 1.0
    return (w.get("recall", 1.0) * s.get("recall_macro", 0.0)
            + w.get("precision", 1.0) * s.get("precision_macro", 0.0)
            + w.get("gate", 1.0) * gate_ratio)


def _by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s.get("scenario_id"): s for s in report.get("scenarios", [])
            if s.get("scenario_id") is not None}


def total_cost(report: dict[str, Any]) -> int | None:
    """跨场景 token 总成本。任一场景缺 token 数据（未启用 --token-cost / 捕获失败）返回 None。"""
    deltas: list[int] = []
    for scenario in report.get("scenarios", []):
        tokens = scenario.get("tokens")
        if not isinstance(tokens, dict) or "total_delta" not in tokens:
            return None
        deltas.append(int(tokens["total_delta"]))
    return sum(deltas)


def compare(base_report: dict[str, Any], cur_report: dict[str, Any],
            weights: dict[str, float] | None = None,
            max_cost_ratio: float | None = None) -> GateVerdict:
    """基线 vs 当前：任何一项回归即不通过（fail-closed）。

    判据（全部满足才 accepted）：
    1. 审计无错误（infra）。
    2. 覆盖不缩水：基线场景必须都在当前跑；新场景必须 full_match。
    3. 逐场景不回归：recall / precision / gate 一致性只许持平或变好。
    4. 加权复合分 >= 基线（D3 质量）。
    5. token 成本不超基线 × max_cost_ratio（D3 成本预算；max_cost_ratio=None 时不查）。
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    failures: list[str] = []
    notes: list[str] = []
    base_map = _by_id(base_report)
    cur_map = _by_id(cur_report)
    cur_sum = cur_report.get("summary", {})

    if cur_sum.get("with_audit_errors"):
        failures.append(f"audit errors: {cur_sum['with_audit_errors']} (fail-closed)")

    for sid in base_map:
        if sid not in cur_map:
            failures.append(
                f"coverage regression: baseline scenario {sid!r} missing from current run")
    for sid in cur_map:
        if sid not in base_map:
            s = cur_map[sid]
            if s.get("full_match"):
                notes.append(f"new scenario {sid!r} full_match (new coverage, ok)")
            else:
                failures.append(
                    f"new scenario {sid!r} not full_match "
                    f"(recall={s.get('recall'):.2f} precision={s.get('precision'):.2f})")

    for sid, base in base_map.items():
        cur = cur_map.get(sid)
        if cur is None:
            continue
        if cur.get("recall", 0.0) + _EPS < base.get("recall", 0.0):
            failures.append(
                f"{sid}: recall {cur['recall']:.2f} < baseline {base['recall']:.2f}")
        if cur.get("precision", 0.0) + _EPS < base.get("precision", 0.0):
            failures.append(
                f"{sid}: precision {cur['precision']:.2f} < baseline {base['precision']:.2f}")
        if base.get("gate_consistent") and not cur.get("gate_consistent"):
            failures.append(
                f"{sid}: gate consistency lost "
                f"(baseline got {base.get('gate_distribution')}, now {cur.get('gate_distribution')})")

    score_base = gate_score(base_report, weights)
    score_cur = gate_score(cur_report, weights)
    if score_cur + _EPS < score_base:
        failures.append(
            f"weighted score {score_cur:.4f} < baseline {score_base:.4f} (weights={weights})")

    cost_base = total_cost(base_report)
    cost_cur = total_cost(cur_report)
    if max_cost_ratio is not None:
        if cost_base is None or cost_cur is None:
            failures.append("cost gate enabled but token data missing "
                            "(run harness with --token-cost on both sides)")
        elif cost_cur > cost_base * max_cost_ratio:
            failures.append(
                f"token cost {cost_cur:,} > baseline {cost_base:,} x {max_cost_ratio}")
    elif cost_base is not None and cost_cur is not None:
        notes.append(
            f"token cost baseline={cost_base:,} current={cost_cur:,} (no budget gate)")

    if not failures:
        notes.append("no regression vs baseline")

    return GateVerdict(accepted=not failures, failures=failures, notes=notes,
                       score_base=score_base, score_cur=score_cur,
                       cost_base=cost_base, cost_cur=cost_cur,
                       weights=weights)


# ---------------------------------------------------------------------------
# pin 读写
# ---------------------------------------------------------------------------

def load_pin(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "baseline" not in data:
        raise ValueError(f"pin file missing 'baseline': {path}")
    return data


def _weights_of(pin: dict[str, Any], cli: dict[str, float | None]) -> dict[str, float]:
    merged = dict(pin.get("weights") or DEFAULT_WEIGHTS)
    for key in DEFAULT_WEIGHTS:
        if cli.get(key) is not None:
            merged[key] = float(cli[key])
    return merged


def write_pin(path: Path, report: dict[str, Any], weights: dict[str, float],
              project_root: Path = PROJECT_ROOT, eval_root: Path = EVAL_ROOT) -> dict[str, Any]:
    pin = {
        "schema_version": "1",
        "argus_version": git_short_sha(project_root),
        "engine_fingerprint": engine_fingerprint(project_root),
        "eval_fingerprint": eval_fingerprint(eval_root),
        "weights": {k: float(weights.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS},
        "pinned_date": datetime.date.today().isoformat(),
        "baseline": report,
    }
    path.write_text(json.dumps(pin, ensure_ascii=False, indent=2), encoding="utf-8")
    return pin


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-gate", description="Argus v2 评测门禁（R5.2）")
    parser.add_argument("--pin", action="store_true",
                        help="建立/推进 pin（默认只在门禁通过时允许）")
    parser.add_argument("--force", action="store_true",
                        help="门禁未过仍强制推进 pin（需 --pin，显式知情）")
    parser.add_argument("--json", default="",
                        help="消费 harness --json-out 的报告，不重跑评测")
    parser.add_argument("--pin-file", default=str(Path(EVAL_ROOT) / PIN_NAME))
    parser.add_argument("--eval-root", default=str(EVAL_ROOT))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--engine", choices=["local", "agentteams"], default="local")
    parser.add_argument("--python", default="",
                        help="Python 解释器路径（默认 sys.executable，仅重跑评测时用）")
    parser.add_argument("--timeout", type=int, default=300)
    for key, label in (("recall", "召回"), ("precision", "精确"), ("gate", "gate 一致性")):
        parser.add_argument(f"--weight-{key}", type=float, default=None,
                            help=f"D3 {label} 权重（默认 1.0，仅本次对比生效）")
    parser.add_argument("--max-cost-ratio", type=float, default=None,
                        help="token 成本预算：当前总成本 > 基线×ratio 即拒绝 "
                             "（默认不查成本；需 harness --token-cost 双方都有数据）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pin_path = Path(args.pin_file)
    eval_root = Path(args.eval_root)
    cli_weights = {"recall": args.weight_recall,
                   "precision": args.weight_precision,
                   "gate": args.weight_gate}

    if args.json:
        try:
            cur_report = json.loads(Path(args.json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[argus-gate] cannot read --json: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        if "summary" not in cur_report or "scenarios" not in cur_report:
            print("[argus-gate] --json file is not an argus-eval report "
                  "(missing summary/scenarios)", file=sys.stderr)
            return EXIT_CONFIG
    else:
        scenarios = load_manifest(eval_root)
        cur_report = run_evaluation(
            eval_root, scenarios, args.runs, args.engine,
            args.python or sys.executable, args.timeout)
        for s in cur_report["scenarios"]:
            print(render_result(s))

    if not pin_path.exists():
        if not args.pin:
            print(f"[argus-gate] no pin at {pin_path}; "
                  f"run with --pin to establish baseline", file=sys.stderr)
            return EXIT_NO_PIN
        weights = _weights_of({"weights": None}, cli_weights)
        pin = write_pin(pin_path, cur_report, weights)
        _print_pin_header("baseline pinned", pin)
        return EXIT_PASS

    try:
        pin = load_pin(pin_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[argus-gate] cannot read pin {pin_path}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    cur_eval_fp = eval_fingerprint(eval_root)
    if cur_eval_fp != pin.get("eval_fingerprint"):
        print(f"[argus-gate] EVAL SET CHANGED since pin: "
              f"\n  pinned {pin.get('eval_fingerprint')}\n  now    {cur_eval_fp}")
        print("[argus-gate] measurement baseline changed; 需重 pin 后才可对比 "
              "(--pin --force 确认重 pin)", file=sys.stderr)
        if args.pin and args.force:
            print("[argus-gate] force re-pin acknowledged")
        else:
            return EXIT_FAIL

    weights = _weights_of(pin, cli_weights)
    verdict = compare(pin["baseline"], cur_report, weights,
                      max_cost_ratio=args.max_cost_ratio)

    print(f"[argus-gate] version current={git_short_sha()} "
          f"pinned={pin.get('argus_version')}")
    print(f"[argus-gate] score current={verdict.score_cur:.4f} "
          f"pinned={verdict.score_base:.4f} weights={weights}")
    if verdict.cost_base is not None or verdict.cost_cur is not None:
        print(f"[argus-gate] token_cost current={verdict.cost_cur:,} "
              f"pinned={verdict.cost_base:,} "
              f"max_ratio={args.max_cost_ratio}")
    for failure in verdict.failures:
        print(f"[argus-gate]   FAIL {failure}")
    for note in verdict.notes:
        print(f"[argus-gate]   ok  {note}")

    if verdict.accepted:
        if args.pin:
            pin = write_pin(pin_path, cur_report, weights)
            _print_pin_header("gate passed; pin advanced", pin)
        print(f"[argus-gate] GATE PASS")
        return EXIT_PASS

    if args.pin and args.force:
        pin = write_pin(pin_path, cur_report, weights)
        _print_pin_header("gate FAILED but --force; pin forced", pin)
        print("[argus-gate] GATE PASS (forced)")
        return EXIT_PASS
    print("[argus-gate] GATE FAIL")
    return EXIT_FAIL


def _print_pin_header(what: str, pin: dict[str, Any]) -> None:
    print(f"[argus-gate] {what}: version={pin.get('argus_version')} "
          f"engine_fp={pin.get('engine_fingerprint', '')[:20]}... "
          f"eval_fp={pin.get('eval_fingerprint', '')[:20]}...")


if __name__ == "__main__":
    raise SystemExit(main())
