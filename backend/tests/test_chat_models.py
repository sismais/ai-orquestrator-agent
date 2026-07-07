import src.models  # noqa: F401
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from src.database import Base


async def test_chat_tables_created():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "chat_session" in tables
    assert "chat_message" in tables
    await engine.dispose()
