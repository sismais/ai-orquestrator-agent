import pytest
import src.models  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.repositories.decision_repository import DecisionRepository


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def test_add_e_recent_for_project(maker):
    async with maker() as s:
        repo = DecisionRepository(s)
        await repo.add(project_id="p1", card_id="c1", question="Qual banco?",
                       decision="SQLite unico", source="human", stage="plan")
        await repo.add(project_id="p1", card_id="c2", question="Qual auth?",
                       decision="Sem auth (single-user)", source="clarifier", score=2,
                       sources=["AGENTS.md"], stage="specify")
        await repo.add(project_id="OUTRO", card_id="c3", question="X?",
                       decision="Y", source="human", stage="plan")
        await s.commit()

        rows = await repo.recent_for_project("p1", limit=10)
        assert len(rows) == 2                      # escopado por projeto
        assert rows[0].question == "Qual auth?"    # mais recente primeiro
        assert rows[0].score == 2
        assert rows[0].sources == ["AGENTS.md"]


async def test_format_decisions_block(maker):
    from src.repositories.decision_repository import format_decisions_block
    async with maker() as s:
        repo = DecisionRepository(s)
        await repo.add(project_id="p1", card_id="c1", question="Qual banco?",
                       decision="SQLite unico", source="human", stage="plan")
        await s.commit()
        rows = await repo.recent_for_project("p1")
    block = format_decisions_block(rows)
    assert "Qual banco?" in block
    assert "SQLite unico" in block
    assert format_decisions_block([]) == ""
