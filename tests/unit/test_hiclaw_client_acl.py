import pytest

from agentteams.hiclaw_client import HiclawClient, HiclawError


def _check(path, writer=None):
    return HiclawClient._shared_relative(path, writer)


def test_writer_can_write_own_artifact():
    assert _check("projects/p1/dep-findings.json", "dep").as_posix() == "projects/p1/dep-findings.json"
    assert _check("projects/p1/meta-decisions.json", "meta").as_posix() == "projects/p1/meta-decisions.json"
    assert _check("projects/p1/report.json", "synth").as_posix() == "projects/p1/report.json"


def test_writer_cannot_write_other_agent_artifact():
    with pytest.raises(HiclawError, match="not allowed"):
        _check("projects/p1/report.json", "dep")
    with pytest.raises(HiclawError, match="not allowed"):
        _check("projects/p1/sec-findings.json", "dep")
    with pytest.raises(HiclawError, match="not allowed"):
        _check("projects/p1/meta-decisions.json", "sec")


def test_unknown_writer_rejected():
    with pytest.raises(HiclawError, match="unknown writer"):
        _check("projects/p1/report.json", "ghost")


def test_no_writer_means_no_acl_but_still_blocks_traversal():
    # 无 writer 不校验 ACL（向后兼容），但路径安全校验仍生效。
    assert _check("projects/p1/anything.json").as_posix() == "projects/p1/anything.json"
    with pytest.raises(HiclawError, match="unsafe"):
        _check("../etc/passwd")
