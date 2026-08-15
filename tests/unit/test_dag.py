from core.dag import (
    Dag, DagNode, build_default_dag, validate_dag, validate_dag_structure,
    validate_or_fallback,
)


def _dag(*nodes):
    return Dag(nodes=tuple(nodes))


def test_valid_dag_passes():
    d = _dag(
        DagNode(id="assess-sec", agent="sec", inputs=(), critical=True),
        DagNode(id="assess-dep", agent="dep", inputs=(), critical=True),
        DagNode(id="assess-delivery", agent="delivery", inputs=(), critical=True),
        DagNode(id="meta", agent="meta", inputs=("assess-sec", "assess-dep", "assess-delivery")),
        DagNode(id="synth", agent="synth", inputs=("meta",)),
    )
    v = validate_dag(d)
    assert v.valid, v.errors
    assert not v.warnings  # 无孤立节点


def test_cycle_detected():
    d = _dag(
        DagNode(id="a", agent="sec", inputs=("b",)),
        DagNode(id="b", agent="dep", inputs=("a",)),
    )
    v = validate_dag_structure(d)
    assert not v.valid
    assert any("cycle" in e for e in v.errors)


def test_self_loop_detected():
    d = _dag(DagNode(id="a", agent="sec", inputs=("a",)))
    v = validate_dag_structure(d)
    assert not v.valid
    assert any("cycle" in e for e in v.errors)


def test_dangling_dependency_detected():
    d = _dag(DagNode(id="a", agent="sec", inputs=("ghost",)))
    v = validate_dag_structure(d)
    assert not v.valid
    assert any("unknown node" in e for e in v.errors)


def test_isolated_node_warns():
    d = _dag(
        DagNode(id="a", agent="sec", inputs=("b",)),
        DagNode(id="b", agent="dep", inputs=()),
        DagNode(id="lonely", agent="code", inputs=()),
    )
    v = validate_dag_structure(d)
    assert v.valid  # 孤立只是告警不阻断
    assert any("isolated" in w for w in v.warnings)


def test_duplicate_task_detected():
    d = _dag(
        DagNode(id="x", agent="sec", inputs=("i",)),
        DagNode(id="y", agent="sec", inputs=("i",)),
        DagNode(id="i", agent="dep", inputs=()),
    )
    v = validate_dag_structure(d)
    assert not v.valid
    assert any("duplicate task" in e for e in v.errors)


def test_mandatory_agent_missing_blocks():
    d = _dag(
        DagNode(id="meta", agent="meta", inputs=()),
        DagNode(id="synth", agent="synth", inputs=("meta",)),
    )
    v = validate_dag(d)
    assert not v.valid
    assert any("mandatory agent missing" in e for e in v.errors)


def test_fallback_to_default_dag_on_invalid():
    bad = _dag(
        DagNode(id="a", agent="sec", inputs=("b",)),
        DagNode(id="b", agent="dep", inputs=("a",)),
    )
    dag, result, used_fallback = validate_or_fallback(
        bad, default_agents={"sec", "dep", "code", "delivery"})
    assert used_fallback
    assert not result.valid
    # fallback 是合法 DAG 且覆盖全部 assessor + meta + synth
    assert {n.agent for n in dag.nodes} >= {"sec", "dep", "code", "delivery",
                                             "meta", "synth"}
    assert validate_dag(dag).valid


def test_no_fallback_when_valid():
    ok = _dag(
        DagNode(id="sec", agent="sec", inputs=(), critical=True),
        DagNode(id="dep", agent="dep", inputs=(), critical=True),
        DagNode(id="delivery", agent="delivery", inputs=(), critical=True),
        DagNode(id="meta", agent="meta", inputs=("sec", "dep", "delivery")),
        DagNode(id="synth", agent="synth", inputs=("meta",)),
    )
    dag, result, used_fallback = validate_or_fallback(ok)
    assert not used_fallback
    assert dag is ok
    assert result.valid


def test_default_dag_is_valid_and_ordered():
    d = build_default_dag({"sec", "dep", "code", "delivery"})
    assert validate_dag(d).valid
    meta = next(n for n in d.nodes if n.id == "meta")
    synth = next(n for n in d.nodes if n.id == "synth")
    assert set(meta.inputs) == {f"assess-{a}" for a in ("sec", "dep", "code", "delivery")}
    assert synth.inputs == ("meta",)
