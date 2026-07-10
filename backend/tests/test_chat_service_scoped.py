import src.models  # noqa: F401
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
from src.models.project_registry import Project
from src.repositories.chat_repository import ChatRepository


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_send_message_persists_and_uses_project_cwd(maker, monkeypatch):
    import src.services.chat_service as cs
    monkeypatch.setattr(cs, "async_session_maker", maker)

    async with maker() as s:
        s.add(Project(id="p1", name="X", path="/repo/x"))
        await s.commit()
        repo = ChatRepository(s)
        chat = await repo.create_session(project_id="p1")
        await s.commit()
        session_id = chat.id

    captured = {}

    async def fake_stream(messages, model, system_prompt, cwd):
        captured["cwd"] = cwd
        yield "ola"

    service = cs.ChatService()
    monkeypatch.setattr(service.claude_agent, "stream_response", fake_stream)

    chunks = [c async for c in service.send_message(session_id=session_id, message="oi", model="sonnet-5")]
    assert any(c.get("type") == "chunk" for c in chunks)
    assert captured["cwd"] == "/repo/x"

    async with maker() as s:
        msgs = await ChatRepository(s).get_messages(session_id)
    assert [m.role for m in msgs] == ["user", "assistant"]


async def test_contexto_inclui_colunas_do_workflow_real(maker, monkeypatch):
    """Cards em paused/validate_ci/ready_to_merge aparecem no contexto do chat (A6)."""
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project
    from src.repositories.card_repository import CardRepository
    from src.schemas.card import CardCreate

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev"))
        repo = CardRepository(s)
        c1 = await repo.create(CardCreate(title="Tarefa pausada"), project_id="p1")
        c1.column_id = "paused"
        c2 = await repo.create(CardCreate(title="Aguardando merge"), project_id="p1")
        c2.column_id = "ready_to_merge"
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    ctx = await cs.ChatService()._get_kanban_context("p1")
    assert "Tarefa pausada" in ctx
    assert "Aguardando merge" in ctx


async def test_atividades_escopadas_por_projeto(maker, monkeypatch):
    """Atividade de outro projeto NAO vaza para o contexto do chat (A6)."""
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project
    from src.repositories.card_repository import CardRepository
    from src.repositories.activity_repository import ActivityRepository
    from src.schemas.card import CardCreate

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj1", path="/tmp/p1", workflow_id="dev"))
        s.add(Project(id="p2", name="proj2", path="/tmp/p2", workflow_id="dev"))
        repo = CardRepository(s)
        await repo.create(CardCreate(title="Do projeto 1"), project_id="p1")
        c2 = await repo.create(CardCreate(title="SEGREDO do projeto 2"), project_id="p2")
        await ActivityRepository(s).add_comment(c2.id, "human", "comentario p2")
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    ctx = await cs.ChatService()._get_kanban_context("p1")
    assert "SEGREDO do projeto 2" not in ctx


async def test_system_prompt_contem_projectid_e_worktrees(maker, monkeypatch):
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev"))
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    sp = await cs.ChatService().get_system_prompt("p1")
    assert '"projectId": "p1"' in sp
    assert ".worktrees/" in sp
    assert "/api/activities/card/" in sp
