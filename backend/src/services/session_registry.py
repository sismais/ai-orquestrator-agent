"""Registry das sessoes de agente ativas (uma por card), para Stop/mensagem ao vivo.

A pipeline roda sequencial por card -> no maximo 1 sessao ativa por card. O `stage_runner`
registra o `ClaudeSDKClient` enquanto a etapa roda; a camada HTTP alcanca esse cliente por aqui
para `interrupt()` (Stop) ou `query()` (falar ao vivo). Estado em memoria do processo.
"""

from typing import Optional

# card_id -> ClaudeSDKClient (tipado como object p/ nao acoplar o import do SDK aqui)
_active: dict[str, object] = {}
_interrupted: dict[str, bool] = {}
_pending_says: dict[str, int] = {}  # mensagens do humano injetadas aguardando resposta do agente


def register(card_id: str, client: object) -> None:
    _active[card_id] = client
    _interrupted.pop(card_id, None)
    _pending_says.pop(card_id, None)


def unregister(card_id: str) -> None:
    _active.pop(card_id, None)
    _pending_says.pop(card_id, None)


def take_say(card_id: str) -> bool:
    """Consome uma mensagem pendente (True se havia) — o runner recebe a resposta dela."""
    n = _pending_says.get(card_id, 0)
    if n > 0:
        _pending_says[card_id] = n - 1
        return True
    return False


def is_active(card_id: str) -> bool:
    return card_id in _active


def was_interrupted(card_id: str) -> bool:
    return _interrupted.get(card_id, False)


def clear_interrupt(card_id: str) -> None:
    _interrupted.pop(card_id, None)


async def interrupt(card_id: str) -> bool:
    """Marca a flag e envia interrupt pro cliente ativo. False se nao ha sessao ativa."""
    client = _active.get(card_id)
    if client is None:
        return False
    _interrupted[card_id] = True
    try:
        await client.interrupt()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — interrupt best-effort
        pass
    return True


async def say(card_id: str, message: str) -> bool:
    """Injeta uma mensagem do humano na sessao ativa (incremento 2). False se nao ha sessao."""
    client = _active.get(card_id)
    if client is None:
        return False
    try:
        await client.query(message)  # type: ignore[attr-defined]
        _pending_says[card_id] = _pending_says.get(card_id, 0) + 1
        return True
    except Exception:  # noqa: BLE001
        return False


def active_card_ids() -> list[str]:
    return list(_active.keys())


def get(card_id: str) -> Optional[object]:
    return _active.get(card_id)
