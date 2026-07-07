"""Repositorio de chat: sessoes e mensagens por projeto. Segue o padrao do
card_repository (flush sem commit; quem chama commita)."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat import ChatSession, ChatMessage


class ChatRepository:
    """Repository for chat session/message database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self, project_id: str, title: Optional[str] = None) -> ChatSession:
        obj = ChatSession(project_id=project_id, title=title)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        res = await self.session.execute(select(ChatSession).where(ChatSession.id == session_id))
        return res.scalar_one_or_none()

    async def list_sessions(self, project_id: str) -> List[ChatSession]:
        res = await self.session.execute(
            select(ChatSession).where(ChatSession.project_id == project_id).order_by(ChatSession.updated_at.desc())
        )
        return list(res.scalars().all())

    async def add_message(self, session_id: str, role: str, content: str, model: Optional[str] = None) -> ChatMessage:
        obj = ChatMessage(session_id=session_id, role=role, content=content, model=model)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_messages(self, session_id: str) -> List[ChatMessage]:
        res = await self.session.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        )
        return list(res.scalars().all())

    async def delete_session(self, session_id: str) -> bool:
        obj = await self.get_session(session_id)
        if not obj:
            return False
        for m in await self.get_messages(session_id):
            await self.session.delete(m)
        await self.session.delete(obj)
        await self.session.flush()
        return True
