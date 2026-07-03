"""Regras de movimentacao de card derivadas do config do Workflow."""


def is_valid_transition(transitions: dict[str, list[str]], src: str, dst: str) -> bool:
    """True se `dst` esta na lista de destinos permitidos de `src` no config."""
    return dst in transitions.get(src, [])
