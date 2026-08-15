"""AI 网关指标聚合器纯逻辑测试（不依赖 live 网关）。"""
from __future__ import annotations

from agentteams.gateway_metrics import (
    METRIC_PREFIX,
    ConsumerStats,
    TokenTotals,
    aggregate,
    aggregate_token_totals,
    parse_prometheus,
    render_table,
    to_dict,
    token_delta,
)

L = ("{ai_route=\"r.internal\",ai_cluster=\"outbound|443||openai-compat.dns\","
     "ai_model=\"deepseek-v4-flash\",ai_consumer=\"")

FIXTURE = (
    f"# HELP route_upstream_model_consumer_metric_input_token input\n"
    f"# TYPE route_upstream_model_consumer_metric_input_token counter\n"
    f"{METRIC_PREFIX}input_token{L}manager\"}} 1000\n"
    f"{METRIC_PREFIX}input_token{L}worker-argus-sec\"}} 200\n"
    f"{METRIC_PREFIX}output_token{L}manager\"}} 50\n"
    f"{METRIC_PREFIX}output_token{L}worker-argus-sec\"}} 10\n"
    f"{METRIC_PREFIX}llm_duration_count{L}manager\"}} 5\n"
    f"{METRIC_PREFIX}llm_first_token_duration{L}manager\"}} 25000\n"
    f"{METRIC_PREFIX}llm_service_duration{L}manager\"}} 100000\n"
    f"{METRIC_PREFIX}llm_stream_duration_count{L}manager\"}} 95000\n"
    f"envoy_cluster_upstream_rq_total{{cluster=\"x\"}} 999\n"
    f"not_a_metric 1\n"
)


# --- parse_prometheus ---

def test_parse_extracts_consumer_metrics():
    samples = parse_prometheus(FIXTURE)
    by_metric = {(s.metric, s.consumer): s.value for s in samples}
    assert by_metric[("input_token", "manager")] == 1000
    assert by_metric[("input_token", "worker-argus-sec")] == 200
    assert by_metric[("output_token", "manager")] == 50
    assert by_metric[("llm_duration_count", "manager")] == 5
    assert by_metric[("llm_first_token_duration", "manager")] == 25000


def test_parse_ignores_comments_and_unrelated_metrics():
    samples = parse_prometheus(FIXTURE)
    assert all(s.metric in (
        "input_token", "output_token", "llm_duration_count",
        "llm_first_token_duration", "llm_service_duration",
        "llm_stream_duration_count") for s in samples)
    # envoy_cluster_* 与非 AI 指标都被跳过（8 条 consumer 指标全保留）
    assert len(samples) == 8


def test_parse_skips_line_without_consumer_label():
    text = (f"{METRIC_PREFIX}input_token{{ai_model=\"m\"}} 5\n")
    assert parse_prometheus(text) == []


def test_parse_skips_unknown_metric_suffix():
    text = f"{METRIC_PREFIX}mystery_metric{L}manager\"}} 1\n"
    assert parse_prometheus(text) == []


def test_parse_empty_text():
    assert parse_prometheus("# only comments\n\n") == []


# --- aggregate ---

def test_aggregate_sums_per_consumer():
    stats = aggregate(parse_prometheus(FIXTURE))
    manager = stats["manager"]
    sec = stats["worker-argus-sec"]
    assert manager.input_tokens == 1000
    assert manager.output_tokens == 50
    assert manager.total_tokens == 1050
    assert manager.requests == 5
    assert manager.avg_first_token_ms == 25000 / 5
    assert manager.avg_service_ms == 100000 / 5
    assert sec.input_tokens == 200
    assert sec.output_tokens == 10


def test_aggregate_no_requests_no_divide_by_zero():
    stats = aggregate(parse_prometheus(
        f"{METRIC_PREFIX}input_token{L}manager\"}} 10\n"))
    assert stats["manager"].avg_first_token_ms == 0.0
    assert stats["manager"].avg_service_ms == 0.0


# --- render / to_dict ---

def test_render_table_includes_share():
    table = render_table(aggregate(parse_prometheus(FIXTURE)))
    assert "manager" in table
    assert "worker-argus-sec" in table
    # manager 1000/1200 = 83.3%
    assert "83.3%" in table
    assert "avg_first_ms" in table


def test_to_dict_round_numbers():
    data = to_dict(aggregate(parse_prometheus(FIXTURE)))
    assert data["total_input_tokens"] == 1200
    assert data["consumers"]["manager"]["avg_first_token_ms"] == 5000.0
    assert data["consumers"]["manager"]["total_tokens"] == 1050


# --- TokenTotals / aggregate / delta（成本差分用） ---

def test_aggregate_token_totals_sums_across_consumers():
    totals = aggregate_token_totals(aggregate(parse_prometheus(FIXTURE)))
    # manager 1000+200 input, 50+10 output
    assert totals.input_tokens == 1200
    assert totals.output_tokens == 60
    assert totals.total_tokens == 1260


def test_aggregate_token_totals_empty():
    totals = aggregate_token_totals({})
    assert totals == TokenTotals(0, 0, 0)


def test_token_delta_positive():
    d = token_delta(TokenTotals(100, 20, 120), TokenTotals(150, 30, 180))
    assert d == TokenTotals(50, 10, 60)


def test_token_delta_never_negative_on_counter_reset():
    # 网关重启会重置累计计数器 → 差分为负时按 0 处理
    d = token_delta(TokenTotals(1000, 100, 1100), TokenTotals(50, 5, 55))
    assert d == TokenTotals(0, 0, 0)
