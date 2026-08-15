"""DAG 任务编排校验器（R1.1）。

LLM planner 可以自由生成 DAG，但执行前必须过确定性校验器：
- 结构校验：环（DFS 三色标记）、悬空依赖、孤立节点、重复任务（agent + 归一化 inputs）、重复 id；
- 业务校验：MANDATORY_AGENTS 不可被删除（宁多审不少审，P3 fail-closed）。

校验失败不直接执行，回退到静态默认 DAG（assessors -> meta -> synth）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.scheduler import MANDATORY_AGENTS


@dataclass(frozen=True)
class DagNode:
    id: str
    agent: str
    inputs: tuple[str, ...] = ()
    required: bool = True
    critical: bool = False


@dataclass(frozen=True)
class Dag:
    nodes: tuple[DagNode, ...]

    def ids(self) -> set[str]:
        return {n.id for n in self.nodes}


@dataclass(frozen=True)
class DagValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.valid


def _dependents(nodes: tuple[DagNode, ...]) -> dict[str, list[str]]:
    dep: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for inp in n.inputs:
            dep.setdefault(inp, []).append(n.id)
    return dep


def _has_cycle(nodes: tuple[DagNode, ...]) -> list[str]:
    """三色 DFS 找环；返回构成环的节点 id 列表（空 = 无环）。"""
    by_id = {n.id: n for n in nodes}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n.id: WHITE for n in nodes}
    stack_path: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        stack_path.append(u)
        for inp in by_id[u].inputs:
            if color.get(inp) == GRAY:
                # 找到环：从 stack_path 中截取 inp 之后的部分
                start = stack_path.index(inp)
                return stack_path[start:] + [inp]
            if color.get(inp) == WHITE:
                found = dfs(inp)
                if found:
                    return found
        stack_path.pop()
        color[u] = BLACK
        return None

    for nid in by_id:
        if color[nid] == WHITE:
            found = dfs(nid)
            if found:
                return found
    return []


def _normalized_key(node: DagNode) -> tuple[str, tuple[str, ...]]:
    return (node.agent, tuple(sorted(node.inputs)))


def validate_dag_structure(dag: Dag) -> DagValidation:
    nodes = dag.nodes
    errors: list[str] = []
    warnings: list[str] = []

    # 重复 id
    seen_ids: dict[str, int] = {}
    for n in nodes:
        seen_ids[n.id] = seen_ids.get(n.id, 0) + 1
    for nid, count in seen_ids.items():
        if count > 1:
            errors.append(f"duplicate node id: {nid!r} x{count}")

    # 悬空依赖：inputs 引用了不存在的节点
    valid_ids = dag.ids()
    for n in nodes:
        for inp in n.inputs:
            if inp not in valid_ids:
                errors.append(f"node {n.id!r} depends on unknown node {inp!r}")

    # 环
    cycle = _has_cycle(nodes)
    if cycle:
        errors.append("cycle detected: " + " -> ".join(cycle))

    # 孤立节点：无 inputs 且无任何节点依赖它
    dependents = _dependents(nodes)
    for n in nodes:
        if not n.inputs and not dependents.get(n.id):
            warnings.append(f"isolated node (no edges): {n.id!r}")

    # 重复任务：agent + 归一化 inputs 相同
    key_count: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for n in nodes:
        key_count.setdefault(_normalized_key(n), []).append(n.id)
    for key, ids in key_count.items():
        if len(ids) > 1:
            errors.append(
                f"duplicate task (agent={key[0]!r}, inputs={key[1]}): {ids}")

    return DagValidation(valid=not errors, errors=tuple(errors),
                         warnings=tuple(warnings))


def validate_dag(dag: Dag, *, required_agents: set[str] | None = None) -> DagValidation:
    """结构校验 + 业务校验（MANDATORY_AGENTS 不可缺失）。"""
    structural = validate_dag_structure(dag)
    errors = list(structural.errors)
    warnings = list(structural.warnings)

    agents_present = {n.agent for n in dag.nodes}
    # 业务约束：mandatory 必须覆盖（宁多审不少审）；required 缺失只告警不阻断
    # （required 缺失在 policy 层会 fail-closed 出 unknown，此处仅提示）。
    for agent in sorted(MANDATORY_AGENTS):
        if agent not in agents_present:
            errors.append(f"mandatory agent missing: {agent!r}")
    if required_agents:
        for agent in sorted(required_agents - agents_present):
            warnings.append(f"required agent not scheduled: {agent!r}")

    return DagValidation(valid=not errors, errors=tuple(errors),
                         warnings=tuple(warnings))


def build_default_dag(agents: set[str]) -> Dag:
    """静态默认 DAG：assessors 并行 -> meta -> synth（宁多审不少审）。"""
    assessor_agents = sorted(a for a in agents if a not in ("meta", "synth"))
    assessors = tuple(
        DagNode(id=f"assess-{a}", agent=a, inputs=(),
                required=True, critical=a in MANDATORY_AGENTS)
        for a in assessor_agents
    )
    meta = DagNode(id="meta", agent="meta",
                   inputs=tuple(a.id for a in assessors),
                   required=True, critical=True)
    synth = DagNode(id="synth", agent="synth", inputs=("meta",),
                    required=True, critical=True)
    return Dag(nodes=assessors + (meta, synth))


def validate_or_fallback(dag: Dag, *, required_agents: set[str] | None = None,
                         default_agents: set[str] | None = None) -> tuple[Dag, DagValidation, bool]:
    """校验 LLM 生成的 DAG，失败回退到静态默认 DAG。

    返回 (最终 DAG, 校验结果, 是否使用了 fallback)。
    """
    result = validate_dag(dag, required_agents=required_agents)
    if result.valid:
        return dag, result, False
    fallback = build_default_dag(default_agents or {n.agent for n in dag.nodes})
    return fallback, result, True
