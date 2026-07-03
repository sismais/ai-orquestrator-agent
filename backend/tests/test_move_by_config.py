import pytest
import uuid
import src.models  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from src.database import Base
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate
from src.services.light_migrations import remap_legacy_columns


@pytest.fixture
async def session_and_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker, engine
    await engine.dispose()


async def test_move_valid_transition_uses_config(session_and_engine):
    maker, _ = session_and_engine
    async with maker() as s:
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="A"))  # no project -> falls back to DEV transitions
        await s.commit()
        # backlog -> plan is valid in DEV_TRANSITIONS
        moved, err = await repo.move(card.id, "plan")
        assert err is None and moved.column_id == "plan"


async def test_move_invalid_transition_rejected(session_and_engine):
    maker, _ = session_and_engine
    async with maker() as s:
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="B"))
        await s.commit()
        # backlog -> done is NOT allowed in DEV_TRANSITIONS
        moved, err = await repo.move(card.id, "done")
        assert moved is None and err is not None and "Invalid transition" in err


async def test_remap_legacy_columns(session_and_engine):
    maker, engine = session_and_engine
    insert_sql = text(
        "INSERT INTO cards (id, title, column_id, model_plan, model_implement, model_test, model_review, "
        "archived, created_at, updated_at, is_fix_card) "
        "VALUES (:i, :title, :column_id, 'opus-4.5', 'opus-4.5', 'opus-4.5', 'opus-4.5', 0, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
    )
    async with maker() as s:
        await s.execute(insert_sql, {"i": str(uuid.uuid4()), "title": "T", "column_id": "test"})
        await s.execute(insert_sql, {"i": str(uuid.uuid4()), "title": "C", "column_id": "completed"})
        await s.commit()
    await remap_legacy_columns(engine)
    await remap_legacy_columns(engine)  # idempotente
    async with maker() as s:
        cols = [r[0] for r in (await s.execute(text("SELECT column_id FROM cards ORDER BY title"))).all()]
    assert cols == ["done", "review"]  # C(completed->done), T(test->review) ordered by title C,T
