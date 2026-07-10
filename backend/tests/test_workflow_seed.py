import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.workflow import Workflow
from src.services.workflow_seed import seed_dev_workflow, DEV_WORKFLOW_ID, DEV_COLUMNS


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
    assert keys == ["paused", "backlog", "plan", "implement", "review",
                    "validate_ci", "ready_to_merge", "done"]
    # transicao do fix-loop existe
    assert "implement" in wf.transitions["review"]


async def test_paused_e_a_primeira_coluna(maker):
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        wf = (await session_get(s)).scalar_one()
    ordered = sorted(wf.columns, key=lambda c: c["order"])
    assert ordered[0]["key"] == "paused"
    assert [c["key"] for c in ordered] == [
        "paused", "backlog", "plan", "implement", "review",
        "validate_ci", "ready_to_merge", "done",
    ]


async def test_seed_atualiza_workflow_existente(maker):
    """Seed e upsert (config-as-code): row existente converge para o codigo."""
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        wf = (await session_get(s)).scalar_one()
        wf.columns = [{"key": "so_uma", "label": "X", "order": 0}]
        await s.commit()
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        wf2 = (await session_get(s)).scalar_one()
    assert len(wf2.columns) == len(DEV_COLUMNS)


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
