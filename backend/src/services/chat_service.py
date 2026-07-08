"""
Chat service for managing chat sessions and conversations.
Sessoes e mensagens sao persistidas em DB (ChatSession/ChatMessage), escopadas
por projeto. O cwd usado no agente vem do path do projeto dono da sessao.
Integra com o Kanban para dar contexto de tarefas/atividades (tambem escopado
por projeto).
"""
from typing import Dict, List, AsyncGenerator
from datetime import datetime, timezone
import uuid
from ..agent_chat import get_claude_agent, DEFAULT_SYSTEM_PROMPT
from ..database import async_session_maker
from ..repositories.card_repository import CardRepository
from ..repositories.activity_repository import ActivityRepository
from ..repositories.chat_repository import ChatRepository
from ..repositories.project_repository import ProjectRepository


class ChatService:
    """Service for managing chat sessions and interactions"""

    def __init__(self):
        """Initialize the chat service."""
        self.claude_agent = get_claude_agent()

    async def create_session(self, project_id: str) -> dict:
        """
        Create a new chat session for a project.

        Args:
            project_id: The project this session belongs to

        Returns:
            dict: Session information with id and createdAt timestamp
        """
        async with async_session_maker() as db:
            repo = ChatRepository(db)
            chat = await repo.create_session(project_id=project_id)
            await db.commit()

            return {
                "sessionId": chat.id,
                "createdAt": chat.created_at,
            }

    async def get_session(self, session_id: str) -> dict | None:
        """
        Get a chat session by ID, with its messages.

        Args:
            session_id: The session ID to retrieve

        Returns:
            dict | None: Session data with messages, or None if not found
        """
        async with async_session_maker() as db:
            repo = ChatRepository(db)
            chat = await repo.get_session(session_id)
            if chat is None:
                return None

            messages = await repo.get_messages(session_id)

            return {
                "sessionId": session_id,
                "project_id": chat.project_id,
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "timestamp": m.created_at.isoformat(),
                        "model": m.model,
                    }
                    for m in messages
                ],
            }

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a chat session.

        Args:
            session_id: The session ID to delete

        Returns:
            bool: True if deleted, False if not found
        """
        async with async_session_maker() as db:
            repo = ChatRepository(db)
            deleted = await repo.delete_session(session_id)
            if deleted:
                await db.commit()
            return deleted

    async def list_sessions(self, project_id: str) -> list:
        """
        List all chat sessions for a project.

        Args:
            project_id: The project to list sessions for

        Returns:
            list: ChatSession records for the project
        """
        async with async_session_maker() as db:
            repo = ChatRepository(db)
            return await repo.list_sessions(project_id)

    def _format_relative_time(self, dt: datetime) -> str:
        """Format datetime as relative time (e.g., 'ha 2 dias')"""
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        diff = now - dt

        if diff.days > 0:
            return f"ha {diff.days} dia{'s' if diff.days > 1 else ''}"

        hours = diff.seconds // 3600
        if hours > 0:
            return f"ha {hours}h"

        minutes = diff.seconds // 60
        if minutes > 0:
            return f"ha {minutes}min"

        return "agora"

    def _truncate(self, text: str, max_length: int = 80) -> str:
        """Truncate text adding ... if needed"""
        if not text:
            return ""
        text = text.replace('\n', ' ').strip()
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."

    async def _get_kanban_context(self, project_id: str) -> str:
        """Fetch current kanban state for a project and format as context"""
        try:
            async with async_session_maker() as session:
                card_repo = CardRepository(session)
                activity_repo = ActivityRepository(session)

                # Fetch cards scoped to the project
                cards = await card_repo.get_all(project_id=project_id)

                # Fetch recent activities
                activities = await activity_repo.get_recent_activities(limit=5)

                # Group cards by column
                columns: Dict[str, List] = {
                    "backlog": [], "plan": [], "implement": [],
                    "test": [], "review": [], "done": [],
                    "completed": [], "archived": [], "cancelado": []
                }

                for card in cards:
                    if card.column_id in columns:
                        columns[card.column_id].append(card)

                # Build context
                lines = ["=== KANBAN STATUS ==="]

                # Active columns (excluding completed, archived, cancelado)
                column_config = [
                    ("backlog", "Backlog", "📋"),
                    ("plan", "Plan", "📝"),
                    ("implement", "Implement", "🔨"),
                    ("test", "Test", "🧪"),
                    ("review", "Review", "👀"),
                    ("done", "Done", "✅"),
                ]

                for col_id, col_name, emoji in column_config:
                    col_cards = columns[col_id]
                    if col_cards:
                        lines.append(f"\n{emoji} {col_name} ({len(col_cards)}):")
                        for card in col_cards[:5]:  # Limit to 5 cards per column
                            time_str = self._format_relative_time(card.created_at)
                            lines.append(f"  - \"{card.title}\" ({time_str})")
                            if card.description:
                                desc = self._truncate(card.description, 60)
                                lines.append(f"    -> {desc}")

                # Summary
                active_cols = ["backlog", "plan", "implement", "test", "review", "done"]
                summary = " | ".join([f"{len(columns[c])} {c}" for c in active_cols])
                lines.append(f"\n📊 Resumo: {summary}")

                # Recent activities
                if activities:
                    lines.append("\n🕐 Ultimas atividades:")
                    for act in activities[:5]:
                        time_str = self._format_relative_time(
                            datetime.fromisoformat(act["timestamp"])
                        )
                        card_title = self._truncate(act["cardTitle"], 30)

                        if act["type"] == "moved":
                            lines.append(f"  - \"{card_title}\" movido para {act['toColumn']} ({time_str})")
                        elif act["type"] == "completed":
                            lines.append(f"  - \"{card_title}\" concluido ({time_str})")
                        elif act["type"] == "created":
                            lines.append(f"  - \"{card_title}\" criado ({time_str})")
                        else:
                            lines.append(f"  - \"{card_title}\" {act['type']} ({time_str})")

                lines.append("===================")

                return "\n".join(lines)

        except Exception as e:
            print(f"[ChatService] Error getting kanban context: {e}")
            return ""

    async def get_system_prompt(self, project_id: str) -> str:
        """Get system prompt with kanban context scoped to the project"""
        kanban_context = await self._get_kanban_context(project_id)

        if kanban_context:
            return f"{DEFAULT_SYSTEM_PROMPT}\n\n{kanban_context}"

        return DEFAULT_SYSTEM_PROMPT

    async def send_message(
        self,
        session_id: str,
        message: str,
        model: str = "sonnet-5"
    ) -> AsyncGenerator[dict, None]:
        """
        Send a message and stream the response from Claude.

        Resolve o projeto dono da sessao para usar seu path como cwd do
        agente, persiste a mensagem do usuario e a resposta completa do
        assistente em DB.

        Args:
            session_id: The session ID
            message: The user's message
            model: AI model to use for response

        Yields:
            dict: Stream chunks with type, content, and messageId
        """
        async with async_session_maker() as db:
            repo = ChatRepository(db)
            chat = await repo.get_session(session_id)
            if chat is None:
                yield {
                    "type": "error",
                    "error": "Sessao nao encontrada",
                    "messageId": str(uuid.uuid4()),
                }
                return

            project = await ProjectRepository(db).get_by_id(chat.project_id)
            cwd = project.path if project else None

            if not chat.title:
                chat.title = message.strip().split("\n")[0][:60]

            await repo.add_message(session_id, "user", message, model)
            await db.commit()

            claude_messages = [
                {"role": m.role, "content": m.content}
                for m in await repo.get_messages(session_id)
            ]

            system_prompt = await self.get_system_prompt(chat.project_id)

            assistant_content = ""
            assistant_message_id = str(uuid.uuid4())

            try:
                async for chunk in self.claude_agent.stream_response(
                    messages=claude_messages,
                    model=model,
                    system_prompt=system_prompt,
                    cwd=cwd,
                ):
                    assistant_content += chunk

                    yield {
                        "type": "chunk",
                        "content": chunk,
                        "messageId": assistant_message_id,
                    }

                await repo.add_message(session_id, "assistant", assistant_content, model)
                await db.commit()

                yield {
                    "type": "end",
                    "messageId": assistant_message_id,
                }

            except Exception as e:
                error_message = f"Error generating response: {str(e)}"
                print(f"[ChatService] {error_message}")

                yield {
                    "type": "error",
                    "error": str(e),
                    "messageId": assistant_message_id,
                }


# Singleton instance
_chat_service_instance = None


def get_chat_service() -> ChatService:
    """Get or create the ChatService singleton instance"""
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance
