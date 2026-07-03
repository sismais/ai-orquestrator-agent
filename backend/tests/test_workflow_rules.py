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
