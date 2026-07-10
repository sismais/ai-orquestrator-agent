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


def test_get_profile_conhecido():
    from src.config.model_ids import get_profile
    p = get_profile("fable-5")
    assert p.model_id == "claude-fable-5"
    assert p.fallback_alias == "opus-4.8"


def test_get_profile_desconhecido_usa_default():
    from src.config.model_ids import get_profile, _FALLBACK
    p = get_profile("inexistente-9")
    assert p.model_id == _FALLBACK
    p2 = get_profile(None)
    assert p2.model_id == _FALLBACK


def test_opus_nao_tem_fallback():
    from src.config.model_ids import get_profile
    assert get_profile("opus-4.8").fallback_alias is None


def test_resolve_model_id_compat():
    from src.config.model_ids import resolve_model_id
    assert resolve_model_id("opus-4.8") == "claude-opus-4-8[1m]"
    assert resolve_model_id("opus-4.5") == "claude-opus-4-8[1m]"   # legado
    assert resolve_model_id(None) == "claude-sonnet-5[1m]"
    assert resolve_model_id("qualquer") == "claude-sonnet-5[1m]"
