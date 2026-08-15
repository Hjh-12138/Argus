from core.degradation import Degradation, classify_failures, critical_agents
from core.schemas import AgentResult


def _result(agent, status):
    return AgentResult(
        agent=agent, agent_version_id=f"{agent}-v1", status=status, required=True,
        findings=(), input_snapshot_id="s", rule_set_version="1",
        dataset_version="", metrics={},
    )


def test_critical_agents_always_include_mandatory():
    crit = critical_agents()
    assert {"sec", "dep", "delivery"} <= crit
    # planner 只能增加，不能删减 mandatory。
    assert critical_agents({"code", "arch"}) == {"sec", "dep", "delivery", "code", "arch"}


def test_noncritical_failure_degrades(tmp_path):
    results = (_result("code", "failed"),
               _result("sec", "completed"),
               _result("dep", "completed"),
               _result("delivery", "completed"))
    d = classify_failures(results)
    assert d.degraded_agents == ("code",)
    assert d.not_audited_domains == ("code",)
    assert d.blocking_agents == ()
    assert d.can_continue


def test_critical_failure_blocks(tmp_path):
    results = (_result("code", "completed"),
               _result("sec", "failed"),
               _result("dep", "completed"),
               _result("delivery", "completed"))
    d = classify_failures(results)
    assert d.blocking_agents == ("sec",)
    assert d.degraded_agents == ()
    assert not d.can_continue


def test_mixed_failure_classifies_both(tmp_path):
    results = (_result("code", "failed"),
               _result("sec", "failed"),
               _result("dep", "completed"),
               _result("delivery", "completed"))
    d = classify_failures(results)
    assert d.degraded_agents == ("code",)
    assert d.blocking_agents == ("sec",)
    assert not d.can_continue


def test_no_failures_no_degradation(tmp_path):
    results = (_result("code", "completed"), _result("sec", "completed"),
               _result("dep", "completed"), _result("delivery", "completed"))
    d = classify_failures(results)
    assert d == Degradation((), (), ())
    assert d.can_continue
