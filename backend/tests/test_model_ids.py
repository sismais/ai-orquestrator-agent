from src.config.model_ids import resolve_model_id, ALIAS_TO_MODEL_ID


def test_resolve_known_aliases():
    assert resolve_model_id("opus-4.8") == "claude-opus-4-8[1m]"
    assert resolve_model_id("sonnet-5") == "claude-sonnet-5[1m]"
    assert resolve_model_id("haiku-4.5") == "claude-haiku-4-5"
    assert resolve_model_id("fable-5") == "claude-fable-5"


def test_resolve_legacy_aliases_remapped():
    assert resolve_model_id("opus-4.5") == "claude-opus-4-8[1m]"
    assert resolve_model_id("sonnet-4.5") == "claude-sonnet-5[1m]"


def test_resolve_unknown_falls_back_to_sonnet():
    assert resolve_model_id("nao-existe") == "claude-sonnet-5[1m]"
    assert resolve_model_id(None) == "claude-sonnet-5[1m]"
