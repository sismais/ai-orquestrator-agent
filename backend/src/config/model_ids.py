"""Perfis por modelo (padroes Anthropic 4 e 5): alias de UI -> perfil.

Fonte de verdade compartilhada entre o chat (agent_chat) e o pipeline
(stage_runner/pipeline_service). Cada perfil define o id real no SDK, o alias
de fallback para RECUSA (retry automatico com outro modelo — sem isso um card
com recusa trava sem explicacao) e um snippet opcional de system prompt.
O sufixo [1m] seleciona a variante de 1M de contexto (opus 4.8 e sonnet 5 tem).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    fallback_alias: Optional[str] = None  # para onde ir em recusa (None = pausa direto)
    prompt_append: str = ""               # snippet de system prompt especifico do modelo


MODEL_PROFILES: dict[str, ModelProfile] = {
    "opus-4.8": ModelProfile("claude-opus-4-8[1m]"),
    "sonnet-5": ModelProfile("claude-sonnet-5[1m]", fallback_alias="opus-4.8"),
    "haiku-4.5": ModelProfile("claude-haiku-4-5", fallback_alias="opus-4.8"),
    "fable-5": ModelProfile("claude-fable-5", fallback_alias="opus-4.8"),
    # legados remapeados (cards antigos)
    "opus-4.5": ModelProfile("claude-opus-4-8[1m]"),
    "sonnet-4.5": ModelProfile("claude-sonnet-5[1m]", fallback_alias="opus-4.8"),
}

_FALLBACK = "claude-sonnet-5[1m]"
_DEFAULT_PROFILE = ModelProfile(_FALLBACK, fallback_alias="opus-4.8")

# Compat: mapa simples alias->id (consumidores antigos e testes)
ALIAS_TO_MODEL_ID = {alias: p.model_id for alias, p in MODEL_PROFILES.items()}


def get_profile(alias: Optional[str]) -> ModelProfile:
    """Perfil do alias de UI. Desconhecido/None -> perfil default (sonnet-5 1M)."""
    if not alias:
        return _DEFAULT_PROFILE
    return MODEL_PROFILES.get(alias, _DEFAULT_PROFILE)


def resolve_model_id(alias: Optional[str]) -> str:
    """Resolve um alias de UI para o id real do SDK. Desconhecido/None -> fallback."""
    return get_profile(alias).model_id
