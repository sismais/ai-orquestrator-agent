import src.models  # noqa: F401
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
import src.database as database
import src.services.chat_service as cs
from src.models.project_registry import Project


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_maker", maker)
    # chat_service faz "from ..database import async_session_maker" (bind no
    # import), entao o monkeypatch acima nao alcanca a referencia ja ligada
    # la dentro. Precisa patchar tambem no modulo do chat_service.
    monkeypatch.setattr(cs, "async_session_maker", maker)
    async with maker() as s:
        s.add(Project(id="p1", name="X", path="/repo/x"))
        await s.commit()
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_create_session_requires_project_and_lists_scoped(client):
    r = await client.post("/api/chat/sessions", json={"projectId": "p1"})
    assert r.status_code == 200
    sid = r.json()["sessionId"]

    r2 = await client.get("/api/chat/sessions", params={"projectId": "p1"})
    assert r2.status_code == 200
    assert sid in [s["sessionId"] for s in r2.json()["sessions"]]

    r3 = await client.get("/api/chat/sessions", params={"projectId": "p2"})
    assert sid not in [s["sessionId"] for s in r3.json().get("sessions", [])]


async def test_create_session_without_project_is_rejected(client):
    r = await client.post("/api/chat/sessions", json={})
    assert r.status_code == 422
