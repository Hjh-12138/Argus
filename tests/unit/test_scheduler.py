from core.scheduler import heuristic_schedule, Change, MANDATORY_AGENTS


def _change(path, status="modified", doc=False, route=False) -> Change:
    return Change(path=path, status=status,
                  is_comment_or_doc_only=doc, contains_route_or_query=route)


def test_doc_only_returns_empty_intentional_skip():
    d = heuristic_schedule([_change("README.md", doc=True)])
    assert d.intentional_skip is True
    assert d.agents == set()


def test_code_change_schedules_code_and_sec_for_route():
    d = heuristic_schedule([_change("app/main.py", route=True)])
    assert "code" in d.agents
    assert "sec" in d.agents


def test_pyproject_schedules_dep_and_delivery():
    d = heuristic_schedule([_change("pyproject.toml")])
    assert {"dep", "delivery"} <= d.agents


def test_three_directories_triggers_arch():
    d = heuristic_schedule([_change(f"mod{i}/f.py") for i in range(3)])
    assert "arch" in d.agents


def test_empty_changes_falls_back_to_code():
    d = heuristic_schedule([])
    assert d.agents == {"code"}
    assert d.intentional_skip is False


def test_mandatory_agents_subset():
    d = heuristic_schedule([_change("app/routes.py", route=True)])
    assert d.mandatory <= d.agents


def test_env_file_schedules_sec_and_delivery():
    d = heuristic_schedule([_change(".env.example")])
    assert {"sec", "delivery"} <= d.agents
