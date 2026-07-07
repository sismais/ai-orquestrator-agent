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
