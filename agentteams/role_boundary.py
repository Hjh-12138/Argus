"""角色边界四层拦截（R2.2）。

四层（越界操作直接拦截，P1 机器强约束）：
1. 工具白名单 —— WORKERS[agent].skills（已有，worker_payloads.py）
2. 数据写 ACL —— _WRITE_ACL（hiclaw_client.py，R2.1）
3. 数据读范围 —— _READ_ACL（本模块新增）
4. 职责语义校验 —— 动作与角色声明一致性（本模块新增）
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from agentteams.hiclaw_client import _WRITE_ACL
from agentteams.worker_payloads import WORKERS

# 数据读范围（第3层）：agent 可读的共享对象模式。读取比写入宽松——
# meta/synth 需读下游 artifacts，assessor 只能读快照（源码），不能读他人 findings。
_READ_ACL: dict[str, tuple[str, ...]] = {
    "dep": ("projects/*/snapshot.zip", "projects/*/snapshot.id",
            "projects/*/registry-fixture.json"),
    "code": ("projects/*/snapshot.zip", "projects/*/snapshot.id"),
    "sec": ("projects/*/snapshot.zip", "projects/*/snapshot.id"),
    "delivery": ("projects/*/snapshot.zip", "projects/*/snapshot.id"),
    "meta": (
        "projects/*/snapshot.zip", "projects/*/snapshot.id",
        "projects/*/dep-findings.json", "projects/*/findings-dep.md",
        "projects/*/findings-argus-dep.md",
        "projects/*/code-findings.json", "projects/*/findings-code.md",
        "projects/*/findings-argus-code.md",
        "projects/*/sec-findings.json", "projects/*/findings-sec.md",
        "projects/*/findings-argus-sec.md",
        "projects/*/delivery-findings.json", "projects/*/findings-delivery.md",
    ),
    "synth": (
        "projects/*/snapshot.zip", "projects/*/snapshot.id",
        "projects/*/meta-decisions.json", "projects/*/meta-review.md",
        "projects/*/dep-findings.json", "projects/*/findings-dep.md",
        "projects/*/findings-argus-dep.md",
        "projects/*/code-findings.json", "projects/*/findings-code.md",
        "projects/*/findings-argus-code.md",
        "projects/*/sec-findings.json", "projects/*/findings-sec.md",
        "projects/*/findings-argus-sec.md",
        "projects/*/delivery-findings.json", "projects/*/findings-delivery.md",
    ),
}

# 职责语义（第4层）：角色允许的动作。meta 只 verify 不 create_finding/decide_gate。
_ROLE_ACTIONS: dict[str, set[str]] = {
    "dep": {"inspect_dependencies"},
    "code": {"scan_code"},
    "sec": {"scan_secrets"},
    "delivery": {"check_ci"},
    "meta": {"verify_evidence"},
    "synth": {"evaluate_policy", "materialize_report"},
}


@dataclass(frozen=True)
class BoundaryDecision:
    allowed: bool
    layer: str  # skill | write_acl | read_acl | role_action
    reason: str = ""


def skill_whitelisted(agent: str, skill: str) -> bool:
    """第1层：工具白名单。"""
    worker = WORKERS.get(agent)
    return worker is not None and skill in worker.skills


def write_allowed(agent: str, path: str) -> bool:
    """第2层：数据写 ACL。"""
    patterns = _WRITE_ACL.get(agent, ())
    posix = path.replace("\\", "/")
    return any(fnmatch.fnmatch(posix, p) for p in patterns)


def read_allowed(agent: str, path: str) -> bool:
    """第3层：数据读范围。"""
    patterns = _READ_ACL.get(agent, ())
    posix = path.replace("\\", "/")
    return any(fnmatch.fnmatch(posix, p) for p in patterns)


def role_action_allowed(agent: str, action: str) -> bool:
    """第4层：职责语义校验。"""
    return action in _ROLE_ACTIONS.get(agent, set())


def check_role_boundary(agent: str, *, action: str | None = None,
                        path: str | None = None,
                        mode: str | None = None) -> BoundaryDecision:
    """统一入口：按 mode 依次校验对应层，任一越界即拒绝。"""
    if action is not None:
        if not role_action_allowed(agent, action):
            return BoundaryDecision(False, "role_action",
                                    f"{agent!r} may not perform {action!r}")
    if mode == "write" and path is not None:
        if not write_allowed(agent, path):
            return BoundaryDecision(False, "write_acl",
                                    f"{agent!r} may not write {path!r}")
    if mode == "read" and path is not None:
        if not read_allowed(agent, path):
            return BoundaryDecision(False, "read_acl",
                                    f"{agent!r} may not read {path!r}")
    return BoundaryDecision(True, "skill" if action is None and mode is None else
                            (mode or "role_action"))
