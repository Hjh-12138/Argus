"""AI 网关（Higress ai-statistics）指标聚合器。

从 AgentTeams AI 网关的 Prometheus 端点抓取 `route_upstream_model_consumer_metric_*`
系列指标，按 `ai_consumer` 聚合出每 agent 的 token 用量 / 请求数 / 平均首 token
延迟 / 平均服务耗时。

数据源是 AgentTeams 自带的 Higress `ai-statistics` wasm —— 不是我们插桩的，
纯计数、无 prompt 正文（P4 天然成立）。这是 R4.2「token 占比 / 瓶颈」的最小落地，
输出可直接喂给 R5 评测门禁的 D3 成本维度。

取数通道（二选一）:
  --endpoint 直接 HTTP（容器内/网络可达时，默认 http://agentteams-controller:15020/stats/prometheus）
  --container 通过 `docker exec <container> curl localhost:15020/stats/prometheus`（宿主机用）

用法:
    python -m agentteams.gateway_metrics --container agentteams-controller
    python -m agentteams.gateway_metrics --container agentteams-controller --json-out .argus/gateway-metrics.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass

METRIC_PREFIX = "route_upstream_model_consumer_metric_"
KNOWN_METRICS = {
    "input_token", "output_token", "total_token",
    "llm_duration_count", "llm_first_token_duration",
    "llm_service_duration", "llm_stream_duration_count",
}
DEFAULT_ENDPOINT = "http://agentteams-controller:15020/stats/prometheus"

_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_:]+)\{(?P<labels>[^}]*)\} "
    r"(?P<value>[-+0-9.eE]+)$")
_LABEL_RE = re.compile(r'(?P<key>[A-Za-z0-9_]+)="(?P<value>[^"]*)"')


@dataclass(frozen=True)
class Sample:
    metric: str
    consumer: str
    model: str
    value: float


@dataclass
class ConsumerStats:
    consumer: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    first_token_ms: float = 0.0
    service_ms: float = 0.0
    stream_duration_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def avg_first_token_ms(self) -> float:
        return self.first_token_ms / self.requests if self.requests else 0.0

    @property
    def avg_service_ms(self) -> float:
        return self.service_ms / self.requests if self.requests else 0.0


def parse_prometheus(text: str) -> list[Sample]:
    """解析 Prometheus 文本格式，只取 AI 网关 consumer 指标。"""
    samples: list[Sample] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        if not name.startswith(METRIC_PREFIX):
            continue
        short = name[len(METRIC_PREFIX):]
        if short not in KNOWN_METRICS:
            continue
        labels = dict(_LABEL_RE.findall(match.group("labels")))
        consumer = labels.get("ai_consumer")
        if consumer is None:
            continue
        samples.append(Sample(
            metric=short, consumer=consumer,
            model=labels.get("ai_model", ""),
            value=float(match.group("value"))))
    return samples


def aggregate(samples: list[Sample]) -> dict[str, ConsumerStats]:
    stats: dict[str, ConsumerStats] = {}
    for sample in samples:
        stat = stats.setdefault(
            sample.consumer,
            ConsumerStats(consumer=sample.consumer, model=sample.model))
        if sample.metric == "input_token":
            stat.input_tokens += int(sample.value)
        elif sample.metric == "output_token":
            stat.output_tokens += int(sample.value)
        elif sample.metric == "llm_duration_count":
            stat.requests += int(sample.value)
        elif sample.metric == "llm_first_token_duration":
            stat.first_token_ms += sample.value
        elif sample.metric == "llm_service_duration":
            stat.service_ms += sample.value
        elif sample.metric == "llm_stream_duration_count":
            stat.stream_duration_ms += sample.value
    return stats


def render_table(stats: dict[str, ConsumerStats]) -> str:
    total_input = sum(s.input_tokens for s in stats.values())
    header = (f"{'consumer':<18}{'input':>12}{'output':>10}{'reqs':>8}"
              f"{'avg_first_ms':>13}{'avg_svc_ms':>12}{'in_share':>9}")
    lines = [header]
    for consumer in sorted(stats):
        s = stats[consumer]
        share = s.input_tokens / total_input if total_input else 0.0
        lines.append(
            f"{consumer:<18}{s.input_tokens:>12,}{s.output_tokens:>10,}"
            f"{s.requests:>8,}{s.avg_first_token_ms:>13,.0f}"
            f"{s.avg_service_ms:>12,.0f}{share:>8.1%}")
    return "\n".join(lines)


def fetch_http(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


def fetch_via_docker(container: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", container, "sh", "-c",
         "curl -s -m 10 http://localhost:15020/stats/prometheus"],
        capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker exec {container} failed: {proc.stderr[:300]}")
    return proc.stdout


def to_dict(stats: dict[str, ConsumerStats]) -> dict:
    return {
        "consumers": {
            consumer: {
                "model": s.model,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.total_tokens,
                "requests": s.requests,
                "avg_first_token_ms": round(s.avg_first_token_ms, 1),
                "avg_service_ms": round(s.avg_service_ms, 1),
                "stream_duration_ms": round(s.stream_duration_ms, 1),
            }
            for consumer, s in sorted(stats.items())
        },
        "total_input_tokens": sum(s.input_tokens for s in stats.values()),
    }


@dataclass(frozen=True)
class TokenTotals:
    """全量 token 计数快照（跨所有 ai_consumer 求和）。"""
    input_tokens: int
    output_tokens: int
    total_tokens: int


def aggregate_token_totals(stats: dict[str, ConsumerStats]) -> TokenTotals:
    return TokenTotals(
        input_tokens=sum(s.input_tokens for s in stats.values()),
        output_tokens=sum(s.output_tokens for s in stats.values()),
        total_tokens=sum(s.total_tokens for s in stats.values()),
    )


def fetch_token_totals(container: str = "", endpoint: str = DEFAULT_ENDPOINT) -> TokenTotals:
    """抓取当前全量 token 计数（累计计数器，用于评测前后差分）。"""
    text = fetch_via_docker(container) if container else fetch_http(endpoint)
    return aggregate_token_totals(aggregate(parse_prometheus(text)))


def token_delta(before: TokenTotals, after: TokenTotals) -> TokenTotals:
    """累计计数器求差；不回落到负值。"""
    return TokenTotals(
        input_tokens=max(0, after.input_tokens - before.input_tokens),
        output_tokens=max(0, after.output_tokens - before.output_tokens),
        total_tokens=max(0, after.total_tokens - before.total_tokens),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gateway-metrics", description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--container", default="",
                        help="docker exec 取数（宿主机用），覆盖 --endpoint")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    try:
        text = (fetch_via_docker(args.container)
                if args.container else fetch_http(args.endpoint))
        stats = aggregate(parse_prometheus(text))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[gateway-metrics] ERROR: {exc}", file=sys.stderr)
        return 1
    if not stats:
        print("[gateway-metrics] no AI gateway consumer metrics found "
              "(is ai-statistics enabled / has there been LLM traffic?)",
              file=sys.stderr)
        return 1

    print(render_table(stats))
    if args.json_out:
        import os
        path = args.json_out
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(to_dict(stats), handle, ensure_ascii=False, indent=2)
        print(f"[gateway-metrics] json={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
