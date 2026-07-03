import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.workflow import Workflow
from src.services.workflow_seed import seed_dev_workflow, DEV_WORKFLOW_ID


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_seed_creates_dev_workflow(maker):
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        wf = (await session_get(s)).scalar_one()
    assert wf.id == DEV_WORKFLOW_ID
    keys = [c["key"] for c in wf.columns]
    assert keys == ["backlog", "plan", "implement", "review",
                    "validate_ci", "ready_to_merge", "done", "paused"]
    # transicao do fix-loop existe
    assert "implement" in wf.transitions["review"]


async def test_seed_is_idempotent(maker):
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        await seed_dev_workflow(s)  # nao duplica
    async with maker() as s:
        count = len((await select_all(s)).scalars().all())
    assert count == 1


# helpers
from sqlalchemy import select as _select
async def session_get(s):
    return await s.execute(_select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID))
async def select_all(s):
    return await s.execute(_select(Workflow))
