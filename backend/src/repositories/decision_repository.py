"""Repositorio da memoria de decisoes (N3). Flush sem commit (quem chama commita)."""

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.decision import Decision


class DecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, project_id: str, question: str, decision: str, source: str,
                  card_id: Optional[str] = None, score: Optional[int] = None,
                  sources: Optional[list] = None, stage: Optional[str] = None) -> Decision:
        row = Decision(project_id=project_id, card_id=card_id, question=question,
                       decision=decision, source=source, score=score, sources=sources,
                       stage=stage)
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent_for_project(self, project_id: str, limit: int = 10) -> list:
        rows = (await self.session.execute(
            select(Decision).where(Decision.project_id == project_id)
            .order_by(desc(Decision.created_at), desc(Decision.id)).limit(limit)
        )).scalars().all()
        return list(rows)


def format_decisions_block(rows: list) -> str:
    """Bloco de prompt com as decisoes anteriores ('' se vazio)."""
    if not rows:
        return ""
    lines = ["Decisoes anteriores deste projeto (respeite-as; NAO re-pergunte o que ja foi decidido):"]
    for r in rows:
        src = f" [fontes: {', '.join(r.sources)}]" if r.sources else ""
        lines.append(f"- P: {r.question}\n  D: {r.decision} ({r.source}{src})")
    return "\n".join(lines)
