import json

from agentteams.orchestrator import _admin_dm_room, _manager_matrix_domain


class FakeClient:
    def __init__(self, manager_record, legacy_room="!legacy:matrix-local.agentteams.io:18080"):
        self.manager_record = manager_record
        self.legacy_room = legacy_room

    def _docker_exec_in(self, container, *args, **kwargs):
        assert container == "agentteams-controller"
        assert args == ("hiclaw", "get", "managers", "default", "-o", "json")
        return json.dumps(self.manager_record)

    def _docker_exec(self, *args, **kwargs):
        assert args == ("cat", "/root/manager-workspace/state.json")
        return json.dumps({"admin_dm_room_id": self.legacy_room})


def test_admin_dm_room_prefers_current_manager_resource():
    client = FakeClient({
        "roomID": "!current:matrix-local.agentteams.io:8080",
        "matrixUserID": "@manager:matrix-local.agentteams.io:8080",
    })

    assert _admin_dm_room(client) == "!current:matrix-local.agentteams.io:8080"


def test_manager_matrix_domain_comes_from_current_identity():
    record = {"matrixUserID": "@manager:matrix-local.agentteams.io:8080"}

    assert _manager_matrix_domain(record) == "matrix-local.agentteams.io:8080"
