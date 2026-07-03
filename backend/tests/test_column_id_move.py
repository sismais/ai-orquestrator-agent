import src.models  # noqa: F401
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def test_move_to_paused_allowed(maker):
    """ColumnId=str + config permite implement->paused (antes o Literal barraria)."""
    async with maker() as s:
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="A"))
        await s.commit()
        await repo.move(card.id, "plan")
        moved, err = await repo.move(card.id, "implement")
        assert err is None
        moved, err = await repo.move(card.id, "paused")
        assert err is None and moved.column_id == "paused"


async def test_move_to_validate_ci_allowed(maker):
    async with maker() as s:
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="B"))
        await s.commit()
        for col in ["plan", "implement", "review", "validate_ci"]:
            moved, err = await repo.move(card.id, col)
            assert err is None, f"{col}: {err}"
        assert moved.column_id == "validate_ci"
