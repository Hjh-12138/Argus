import base64
from pathlib import Path

import pytest

from agentteams.hiclaw_client import HiclawClient, HiclawError


def test_publish_shared_file_transports_exact_binary_bytes(tmp_path):
    source = tmp_path / "snapshot.zip"
    payload = b"PK\x03\x04\x00\xff\r\narchive"
    source.write_bytes(payload)
    calls = []
    client = HiclawClient(container="manager")

    def docker_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return ""

    client._docker_exec = docker_exec
    client.publish_shared_file("projects/proj-1/snapshot.zip", source)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0:2] == ("sh", "-c")
    script = args[2]
    assert script.index('base64 -d > "$tmp"') < script.index('mc cp "$tmp" "$2"')
    assert script.index('mc cp "$tmp" "$2"') < script.index('cp "$tmp" "$1"')
    assert args[-1].endswith("/projects/proj-1/snapshot.zip")
    assert base64.b64decode(kwargs["input_text"]) == payload


def test_publish_shared_file_rejects_missing_source(tmp_path):
    client = HiclawClient(container="manager")
    with pytest.raises(HiclawError, match="shared source file does not exist"):
        client.publish_shared_file(
            "projects/proj-1/snapshot.zip", tmp_path / "missing.zip")


def test_publish_shared_file_rejects_traversal(tmp_path):
    source = tmp_path / "snapshot.zip"
    source.write_bytes(b"x")
    client = HiclawClient(container="manager")
    with pytest.raises(HiclawError):
        client.publish_shared_file("../snapshot.zip", source)
