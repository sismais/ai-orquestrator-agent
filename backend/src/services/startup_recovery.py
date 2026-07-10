"""Recovery no boot (A1b): Executions deixadas RUNNING por um restart viram PAUSED.

Sem isso, um crash/restart do backend deixa o run orfao (RUNNING para sempre) e o
card travado — e POST /answer exige PAUSED, entao nem a retomada manual funciona.
O sweep marca a Execution como PAUSED, move o card para `paused` (se a transicao
permitir) e comenta no card para o humano retomar pela aba Interacao.
"""

from datetime import datetime

from sqlalchemy import select

from ..database import async_session_maker
from ..models.execution import Execution, ExecutionStatus
from ..repositories.activity_repository import ActivityRepository
from ..repositories.card_repository import CardRepository

_RESUME_HINT = (
    "O servidor reiniciou durante a execução. "
    "Responda este comentário para retomar de onde parou."
)


async def recover_orphan_executions(session_maker=async_session_maker) -> int:
    """Marca como PAUSED toda Execution RUNNING (orfa de restart). Devolve o total."""
    async with session_maker() as s:
        rows = (await s.execute(
            select(Execution).where(Execution.status == ExecutionStatus.RUNNING)
        )).scalars().all()
        if not rows:
            return 0
        repo = CardRepository(s)
        for ex in rows:
            ex.status = ExecutionStatus.PAUSED
            ex.workflow_error = "backend reiniciado durante o run | recuperado no boot"
            ex.is_active = False
            ex.completed_at = datetime.utcnow()
            card = await repo.get_by_id(ex.card_id)
            if card and card.column_id != "paused":
                await repo.move(ex.card_id, "paused")  # falha de transicao: card fica onde esta
            try:
                await ActivityRepository(s).add_comment(ex.card_id, "agent", _RESUME_HINT)
            except Exception:  # noqa: BLE001 — comentario e best-effort
                pass
        await s.commit()
        return len(rows)
