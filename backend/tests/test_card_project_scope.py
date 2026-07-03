import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.card import Card


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_cards_isolated_by_project_id(maker):
    async with maker() as s:
        s.add(Card(id=str(uuid.uuid4()), title="A", project_id="proj-A"))
        s.add(Card(id=str(uuid.uuid4()), title="B", project_id="proj-B"))
        await s.commit()
    async with maker() as s:
        rows = (await s.execute(
            select(Card).where(Card.project_id == "proj-A")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "A"


from sqlalchemy import text
from src.services.light_migrations import run_light_migrations


async def test_light_migration_adds_missing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # cria a tabela cards SEM project_id (simula DB legado)
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE cards (id VARCHAR(36) PRIMARY KEY, title VARCHAR(255), column_id VARCHAR(20))"
        ))
    await run_light_migrations(engine)
    await run_light_migrations(engine)  # idempotente: rodar 2x nao quebra
    async with engine.begin() as conn:
        cols = {r[1] for r in await conn.execute(text("PRAGMA table_info(cards)"))}
    assert "project_id" in cols
    await engine.dispose()
