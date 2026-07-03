import pytest
import src.models  # noqa: F401  (registra models no Base.metadata p/ create_all robusto)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.database import Base
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_with_project_id_and_filtered_list(session):
    repo = CardRepository(session)
    await repo.create(CardCreate(title="A"), project_id="proj-A")
    await repo.create(CardCreate(title="B"), project_id="proj-B")
    await session.commit()
    only_a = await repo.get_all(project_id="proj-A")
    assert len(only_a) == 1 and only_a[0].title == "A"
    all_cards = await repo.get_all()  # sem filtro = todos (back-compat)
    assert len(all_cards) == 2
