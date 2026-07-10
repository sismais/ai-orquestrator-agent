import pytest
import src.models  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.models.activity_log import ActivityLog, ActivityType
from src.models.execution import Execution, ExecutionStatus
from src.models.project_registry import Project
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate
from src.services.startup_recovery import recover_orphan_executions


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def _card_running_em(maker, coluna: str) -> str:
    """Card na coluna dada + Execution RUNNING orfa (simula crash do backend)."""
    async with maker() as s:
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev", base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X"), project_id="p1")
        card.column_id = coluna
        s.add(Execution(card_id=card.id, status=ExecutionStatus.RUNNING,
                        command="pipeline", is_active=True, workflow_stage=coluna))
        await s.commit()
        return card.id


async def test_running_orfa_vira_paused_e_card_pausa(maker):
    card_id = await _card_running_em(maker, "implement")
    count = await recover_orphan_executions(session_maker=maker)
    assert count == 1
    async with maker() as s:
        ex = (await s.execute(select(Execution).where(Execution.card_id == card_id))).scalars().first()
        assert ex.status == ExecutionStatus.PAUSED
        assert ex.is_active is False
        assert "reiniciado" in (ex.workflow_error or "")
        card = await CardRepository(s).get_by_id(card_id)
        assert card.column_id == "paused"
        # comentario no card orienta a retomada via aba Interacao
        acts = (await s.execute(select(ActivityLog).where(
            ActivityLog.card_id == card_id,
            ActivityLog.activity_type == ActivityType.COMMENTED,
        ))).scalars().all()
        assert any("reiniciou" in (a.description or "") for a in acts)


async def test_sem_orfas_nao_faz_nada(maker):
    count = await recover_orphan_executions(session_maker=maker)
    assert count == 0


async def test_card_ja_pausado_nao_move_mas_pausa_execution(maker):
    card_id = await _card_running_em(maker, "paused")
    count = await recover_orphan_executions(session_maker=maker)
    assert count == 1
    async with maker() as s:
        ex = (await s.execute(select(Execution).where(Execution.card_id == card_id))).scalars().first()
        assert ex.status == ExecutionStatus.PAUSED
        assert ex.is_active is False
        card = await CardRepository(s).get_by_id(card_id)
        assert card.column_id == "paused"
