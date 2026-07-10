"""costStats do card: prefere o custo real do SDK (execution_cost) ao derivado por tokens.

Review da Task 8 (A5): com model_used/tokens agora populados, o derivado do CostCalculator
cobra preco cheio de input (inclui cache_read, ~10x mais barato na realidade) e inflaria o
chip de custo 5-10x. O derivado fica apenas como fallback para execucoes legadas.
"""

import pytest
import src.models  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.config.pricing import calculate_cost
from src.database import Base
from src.models.execution import Execution, ExecutionStatus
from src.models.project_registry import Project
from src.repositories.card_repository import CardRepository
from src.repositories.execution_repository import ExecutionRepository
from src.schemas.card import CardCreate


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def _make_project_card(maker):
    async with maker() as s:
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev", base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X"), project_id="p1")
        await s.commit()
        return card.id


async def _add_execution(maker, card_id, **fields):
    async with maker() as s:
        s.add(Execution(card_id=card_id, status=ExecutionStatus.SUCCESS, command="pipeline", **fields))
        await s.commit()


async def _cost_stats(maker, card_id):
    async with maker() as s:
        return await ExecutionRepository(s).get_cost_stats_for_card(card_id)


async def test_cost_stats_prefere_custo_real_do_sdk(maker):
    """execution_cost=0.5 manda, mesmo com 1M input tokens (derivado seria ~$5)."""
    card_id = await _make_project_card(maker)
    await _add_execution(
        maker, card_id, workflow_stage="implement", execution_cost=0.5,
        model_used="opus-4.8", input_tokens=1_000_000, output_tokens=1000,
    )

    stats = await _cost_stats(maker, card_id)
    assert stats["totalCost"] == pytest.approx(0.5)
    assert stats["implementCost"] == pytest.approx(0.5)
    assert stats["currency"] == "USD"


async def test_cost_stats_fallback_derivado_sem_execution_cost(maker):
    """Execucao legada (sem execution_cost) continua usando o derivado tokens x preco."""
    card_id = await _make_project_card(maker)
    await _add_execution(
        maker, card_id, workflow_stage="plan", execution_cost=None,
        model_used="opus-4.8", input_tokens=1_000_000, output_tokens=0,
    )

    expected = float(calculate_cost("opus-4.8", 1_000_000, 0))
    assert expected > 0  # sanity: derivado nao-trivial

    stats = await _cost_stats(maker, card_id)
    assert stats["totalCost"] == pytest.approx(expected)
    assert stats["planCost"] == pytest.approx(expected)
