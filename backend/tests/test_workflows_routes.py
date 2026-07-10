import pytest
import src.models  # noqa: F401  (registra todos os models no Base.metadata p/ create_all robusto)
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import src.database as database
from src.database import Base
from src.services.workflow_seed import seed_dev_workflow


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await seed_dev_workflow(s)
    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(database, "get_session", lambda: maker)
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_get_dev_workflow(client):
    r = await client.get("/api/workflows/dev")
    assert r.status_code == 200, r.text
    wf = r.json()["workflow"]
    keys = [c["key"] for c in wf["columns"]]
    assert keys == ["paused", "backlog", "plan", "implement", "review",
                    "validate_ci", "ready_to_merge", "done"]
    assert "implement" in wf["transitions"]["review"]


async def test_get_unknown_workflow_404(client):
    r = await client.get("/api/workflows/inexistente")
    assert r.status_code == 404
