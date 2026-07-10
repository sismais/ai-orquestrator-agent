import pytest
from src.services.workflow_rules import is_valid_transition
from src.services.workflow_seed import DEV_TRANSITIONS


def test_valid_transition_from_config():
    assert is_valid_transition(DEV_TRANSITIONS, "implement", "review") is True


def test_fix_loop_transition_allowed():
    assert is_valid_transition(DEV_TRANSITIONS, "review", "implement") is True


def test_invalid_transition_rejected():
    assert is_valid_transition(DEV_TRANSITIONS, "backlog", "done") is False


def test_unknown_column_rejected():
    assert is_valid_transition(DEV_TRANSITIONS, "inexistente", "done") is False


def test_pause_columns_from_config():
    from src.services.workflow_rules import pause_columns_from
    cols = [
        {"key": "fila", "isPausedState": False},
        {"key": "esperando_humano", "isPausedState": True},
        {"key": "done"},
    ]
    assert pause_columns_from(cols) == {"esperando_humano"}


def test_pause_columns_from_vazio_usa_default():
    from src.services.workflow_rules import pause_columns_from
    assert pause_columns_from([]) == {"paused"}
    assert pause_columns_from(None) == {"paused"}


def test_next_active_column_com_pausa_custom():
    from src.services.workflow_rules import next_active_column
    transitions = {"a": ["esperando_humano", "b"]}
    assert next_active_column(transitions, "a", pause_cols={"esperando_humano"}) == "b"
