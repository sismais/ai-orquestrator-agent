"""Regras de movimentacao de card derivadas do config do Workflow."""


def is_valid_transition(transitions: dict[str, list[str]], src: str, dst: str) -> bool:
    """True se `dst` esta na lista de destinos permitidos de `src` no config."""
    return dst in transitions.get(src, [])


# Estados de pausa por convencao (nao entram no caminho-feliz sequencial do runner).
PAUSE_COLUMNS = {"paused"}


def pause_columns_from(columns) -> set:
    """Colunas de pausa derivadas do config (flag isPausedState). Fallback: {'paused'}."""
    if not columns:
        return set(PAUSE_COLUMNS)
    found = {c["key"] for c in columns if c.get("isPausedState")}
    return found or set(PAUSE_COLUMNS)


def next_active_column(transitions: dict[str, list[str]], current: str,
                       pause_cols: "set | None" = None) -> str | None:
    """Sucessora do caminho-feliz de `current` no config.

    Retorna o primeiro destino de `transitions[current]` que nao e estado de pausa
    (o runner avanca por aqui). `None` quando a coluna e terminal (sem destinos ativos).
    `pause_cols`: colunas de pausa do config (default: convencao PAUSE_COLUMNS).
    """
    pause_cols = pause_cols or PAUSE_COLUMNS
    for dst in transitions.get(current, []):
        if dst not in pause_cols:
            return dst
    return None
