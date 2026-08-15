from agentteams.role_boundary import (
    check_role_boundary, read_allowed, role_action_allowed, skill_whitelisted,
    write_allowed,
)


def test_skill_whitelist_layer():
    assert skill_whitelisted("sec", "argus-secret-scan")
    assert not skill_whitelisted("sec", "argus-dependency-inspect")
    assert not skill_whitelisted("ghost", "argus-secret-scan")


def test_write_acl_layer():
    assert write_allowed("dep", "projects/p1/dep-findings.json")
    assert not write_allowed("dep", "projects/p1/report.json")
    assert write_allowed("synth", "projects/p1/report.json")


def test_read_scope_layer():
    # assessor 不能读他人 findings
    assert read_allowed("dep", "projects/p1/snapshot.zip")
    assert not read_allowed("dep", "projects/p1/sec-findings.json")
    # meta/synth 可读下游 artifacts
    assert read_allowed("meta", "projects/p1/sec-findings.json")
    assert read_allowed("synth", "projects/p1/meta-decisions.json")


def test_role_action_layer():
    assert role_action_allowed("meta", "verify_evidence")
    assert not role_action_allowed("meta", "create_finding")
    assert not role_action_allowed("meta", "decide_gate")
    assert role_action_allowed("synth", "evaluate_policy")


def test_unified_boundary_denies_write_escalation():
    d = check_role_boundary("dep", path="projects/p1/report.json", mode="write")
    assert not d.allowed
    assert d.layer == "write_acl"


def test_unified_boundary_denies_read_escalation():
    d = check_role_boundary("dep", path="projects/p1/meta-decisions.json", mode="read")
    assert not d.allowed
    assert d.layer == "read_acl"


def test_unified_boundary_denies_wrong_role_action():
    d = check_role_boundary("meta", action="decide_gate")
    assert not d.allowed
    assert d.layer == "role_action"


def test_unified_boundary_allows_legitimate_ops():
    assert check_role_boundary("meta", path="projects/p1/sec-findings.json",
                               mode="read").allowed
    assert check_role_boundary("synth", path="projects/p1/report.json",
                               mode="write").allowed
    assert check_role_boundary("meta", action="verify_evidence").allowed
