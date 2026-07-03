import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.database import Base
from src.repositories.project_repository import ProjectRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_and_list(session):
    repo = ProjectRepository(session)
    p = await repo.create(name="GMS Web", path="/repos/gms", workflow_id="dev")
    await session.commit()
    assert p.id and p.workflow_id == "dev" and p.base_branch == "main"
    all_ = await repo.list()
    assert len(all_) == 1 and all_[0].name == "GMS Web"


async def test_get_by_path_is_unique_upsert(session):
    repo = ProjectRepository(session)
    await repo.create(name="A", path="/repos/x")
    await session.commit()
    dup = await repo.get_by_path("/repos/x")
    assert dup is not None and dup.name == "A"


async def test_update_and_delete(session):
    repo = ProjectRepository(session)
    p = await repo.create(name="A", path="/repos/y")
    await session.commit()
    await repo.update(p.id, {"favorite": True, "name": "A2"})
    await session.commit()
    got = await repo.get_by_id(p.id)
    assert got.favorite is True and got.name == "A2"
    assert await repo.delete(p.id) is True
    await session.commit()
    assert await repo.get_by_id(p.id) is None
