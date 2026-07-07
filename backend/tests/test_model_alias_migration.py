import src.models  # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.database import Base
from src.services.light_migrations import remap_legacy_model_aliases


async def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def test_remap_legacy_model_aliases_idempotent():
    engine = await _make_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO cards ("
            "id, title, column_id, model_plan, model_implement, model_test, model_review, "
            "archived, is_fix_card, created_at, updated_at"
            ") VALUES ("
            "'c1', 't', 'backlog', 'opus-4.5', 'sonnet-4.5', 'opus-4.5', 'sonnet-4.5', "
            "0, 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00'"
            ")"
        ))
    await remap_legacy_model_aliases(engine)
    await remap_legacy_model_aliases(engine)
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT model_plan, model_implement, model_test, model_review FROM cards WHERE id='c1'"
        ))).first()
    assert row == ("opus-4.8", "sonnet-5", "opus-4.8", "sonnet-5")
    await engine.dispose()
