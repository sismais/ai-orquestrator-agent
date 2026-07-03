import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.project_registry import Project


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_project_defaults(session):
    p = Project(id=str(uuid.uuid4()), name="GMS Web", path="/repos/gms")
    session.add(p)
    await session.commit()
    got = (await session.execute(select(Project))).scalar_one()
    assert got.rules_file == "AGENTS.md"
    assert got.base_branch == "main"
    assert got.favorite is False
    assert got.workflow_id is None
