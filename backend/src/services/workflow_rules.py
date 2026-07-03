"""Regras de movimentacao de card derivadas do config do Workflow."""


def is_valid_transition(transitions: dict[str, list[str]], src: str, dst: str) -> bool:
    """True se `dst` esta na lista de destinos permitidos de `src` no config."""
    return dst in transitions.get(src, [])


# Estados de pausa por convencao (nao entram no caminho-feliz sequencial do runner).
PAUSE_COLUMNS = {"paused"}


def next_active_column(transitions: dict[str, list[str]], current: str) -> str | None:
    """Sucessora do caminho-feliz de `current` no config.

    Retorna o primeiro destino de `transitions[current]` que nao e estado de pausa
    (o runner avanca por aqui). `None` quando a coluna e terminal (sem destinos ativos).
    """
    for dst in transitions.get(current, []):
        if dst not in PAUSE_COLUMNS:
            return dst
    return None
