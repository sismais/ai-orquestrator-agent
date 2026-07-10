import pytest
import src.models  # noqa: F401  (registra todos os models no Base.metadata p/ create_all robusto rodando o arquivo sozinho)
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import src.database as database
from src.database import Base


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # aponta o get_db do app para o engine de teste
    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(database, "get_session", lambda: maker)
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_register_list_and_delete_project(client):
    # cria
    r = await client.post("/api/registry/projects", json={"name": "GMS Web", "path": "/repos/gms"})
    assert r.status_code == 201, r.text
    pid = r.json()["project"]["id"]
    # lista
    r = await client.get("/api/registry/projects")
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json()["projects"])
    # deleta
    r = await client.delete(f"/api/registry/projects/{pid}")
    assert r.status_code == 200


async def test_create_e_patch_objective(client):
    r = await client.post("/api/registry/projects", json={
        "name": "P", "path": "/tmp/obj-test", "objective": "ERP de gestao"
    })
    assert r.status_code == 201, r.text
    assert r.json()["project"]["objective"] == "ERP de gestao"
    pid = r.json()["project"]["id"]

    r2 = await client.patch(f"/api/registry/projects/{pid}", json={"objective": "novo objetivo"})
    assert r2.status_code == 200
    assert r2.json()["project"]["objective"] == "novo objetivo"
