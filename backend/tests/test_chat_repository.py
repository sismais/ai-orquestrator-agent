import src.models  # noqa: F401
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
from src.repositories.chat_repository import ChatRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed_project(session, pid="p1", path="/repo/x"):
    from src.models.project_registry import Project
    session.add(Project(id=pid, name="X", path=path))
    await session.commit()


async def test_create_and_list_sessions_scoped_by_project(session):
    await _seed_project(session, "p1", "/repo/a")
    await _seed_project(session, "p2", "/repo/b")
    repo = ChatRepository(session)
    s1 = await repo.create_session(project_id="p1", title="oi")
    await repo.create_session(project_id="p2", title="outro")
    await session.commit()
    got = await repo.list_sessions("p1")
    assert [s.id for s in got] == [s1.id]


async def test_add_and_get_messages(session):
    await _seed_project(session, "p1", "/repo/a")
    repo = ChatRepository(session)
    s = await repo.create_session(project_id="p1")
    await repo.add_message(s.id, role="user", content="oi", model="sonnet-5")
    await repo.add_message(s.id, role="assistant", content="ola", model="sonnet-5")
    await session.commit()
    msgs = await repo.get_messages(s.id)
    assert [(m.role, m.content) for m in msgs] == [("user", "oi"), ("assistant", "ola")]
