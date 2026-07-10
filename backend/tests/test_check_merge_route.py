"""Testes da rota POST .../cards/{cid}/check-merge (N6 — deteccao de merge).

O endpoint NUNCA faz merge: so detecta o merge feito no GitHub (via get_pr_state,
aqui monkeypatchado) e, quando MERGED, move o card de ready_to_merge -> done.
Idempotente; so age em card em ready_to_merge com worktree.
"""

import pytest
import src.models  # noqa: F401  (registra os models no Base.metadata)
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import src.database as database
from src.database import Base
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate
from src.services import pr_service


@pytest.fixture
async def client_and_maker(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(database, "get_session", lambda: maker)
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, maker
    await engine.dispose()


# caminho valido no DEV workflow (sem projeto -> DEV_TRANSITIONS) ate cada coluna
_PATH_TO = {
    "backlog": [],
    "ready_to_merge": ["plan", "implement", "review", "validate_ci", "ready_to_merge"],
}


async def _make_card(maker, column: str, worktree: str | None = "/wt") -> str:
    async with maker() as s:
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="T"))
        for col in _PATH_TO[column]:
            _, err = await repo.move(card.id, col)
            assert err is None, f"{col}: {err}"
        card.worktree_path = worktree
        await s.commit()
        return card.id


async def _column_of(maker, card_id: str) -> str:
    async with maker() as s:
        card = await CardRepository(s).get_by_id(card_id)
        return card.column_id


def _url(card_id: str) -> str:
    return f"/api/projects/p1/cards/{card_id}/check-merge"


async def test_check_merge_merged_move_para_done(client_and_maker, monkeypatch):
    client, maker = client_and_maker
    card_id = await _make_card(maker, "ready_to_merge")

    async def fake_state(worktree):
        return "MERGED"
    monkeypatch.setattr(pr_service, "get_pr_state", fake_state)

    r = await client.post(_url(card_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged"] is True and body["moved"] is True and body["state"] == "MERGED"
    assert await _column_of(maker, card_id) == "done"


async def test_check_merge_merged_idempotente(client_and_maker, monkeypatch):
    """Segunda chamada (card ja em done) nao quebra e reporta merged sem re-mover."""
    client, maker = client_and_maker
    card_id = await _make_card(maker, "ready_to_merge")

    async def fake_state(worktree):
        return "MERGED"
    monkeypatch.setattr(pr_service, "get_pr_state", fake_state)

    r1 = await client.post(_url(card_id))
    assert r1.status_code == 200 and r1.json()["moved"] is True

    r2 = await client.post(_url(card_id))
    assert r2.status_code == 200
    # card ja saiu do ready_to_merge; reporta merged=True (esta em done), state N/A, sem mover
    assert r2.json()["merged"] is True and r2.json()["state"] == "N/A"
    assert await _column_of(maker, card_id) == "done"


async def test_check_merge_open_nao_move(client_and_maker, monkeypatch):
    client, maker = client_and_maker
    card_id = await _make_card(maker, "ready_to_merge")

    async def fake_state(worktree):
        return "OPEN"
    monkeypatch.setattr(pr_service, "get_pr_state", fake_state)

    r = await client.post(_url(card_id))
    assert r.status_code == 200, r.text
    assert r.json() == {"merged": False, "state": "OPEN"}
    assert await _column_of(maker, card_id) == "ready_to_merge"


async def test_check_merge_card_fora_de_ready_to_merge(client_and_maker):
    client, maker = client_and_maker
    card_id = await _make_card(maker, "backlog")
    r = await client.post(_url(card_id))
    assert r.status_code == 200, r.text
    assert r.json() == {"merged": False, "state": "N/A"}
    assert await _column_of(maker, card_id) == "backlog"


async def test_check_merge_sem_worktree(client_and_maker):
    client, maker = client_and_maker
    card_id = await _make_card(maker, "ready_to_merge", worktree=None)
    r = await client.post(_url(card_id))
    assert r.status_code == 200, r.text
    assert r.json() == {"merged": False, "state": "UNKNOWN"}
    assert await _column_of(maker, card_id) == "ready_to_merge"


async def test_check_merge_card_inexistente(client_and_maker):
    client, _ = client_and_maker
    r = await client.post(_url("nao-existe"))
    assert r.status_code == 404
