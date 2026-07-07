"""Mapa unico alias -> id real do modelo no Claude Code CLI/SDK.

Fonte de verdade compartilhada entre o chat (agent_chat) e o pipeline
(stage_runner/pipeline_service). O sufixo [1m] seleciona a variante de 1M de
contexto (opus 4.8 e sonnet 5 tem). haiku 4.5 e 200k (sem 1m). fable-5 fica
mapeado mas desabilitado nos pickers (beta).
"""
from typing import Optional

ALIAS_TO_MODEL_ID = {
    "opus-4.8": "claude-opus-4-8[1m]",
    "sonnet-5": "claude-sonnet-5[1m]",
    "haiku-4.5": "claude-haiku-4-5",
    "fable-5": "claude-fable-5",
    # legados remapeados (cards antigos)
    "opus-4.5": "claude-opus-4-8[1m]",
    "sonnet-4.5": "claude-sonnet-5[1m]",
}

_FALLBACK = "claude-sonnet-5[1m]"


def resolve_model_id(alias: Optional[str]) -> str:
    """Resolve um alias de UI para o id real do SDK. Desconhecido/None -> fallback."""
    if not alias:
        return _FALLBACK
    return ALIAS_TO_MODEL_ID.get(alias, _FALLBACK)
