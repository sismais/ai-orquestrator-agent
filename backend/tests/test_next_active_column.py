from src.services.workflow_rules import next_active_column
from src.services.workflow_seed import DEV_TRANSITIONS as T


def test_happy_path_successors():
    assert next_active_column(T, "backlog") == "plan"
    assert next_active_column(T, "plan") == "implement"
    assert next_active_column(T, "implement") == "review"
    assert next_active_column(T, "review") == "validate_ci"
    assert next_active_column(T, "validate_ci") == "ready_to_merge"
    assert next_active_column(T, "ready_to_merge") == "done"


def test_terminal_returns_none():
    assert next_active_column(T, "done") is None


def test_ignores_pause_target():
    # backlog -> [plan, paused] : nunca deve devolver paused
    assert next_active_column(T, "backlog") != "paused"


def test_unknown_column_none():
    assert next_active_column(T, "nao-existe") is None
