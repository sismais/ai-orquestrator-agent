"""Recovery no boot (A1b): Executions deixadas RUNNING por um restart viram PAUSED.

Sem isso, um crash/restart do backend deixa o run orfao (RUNNING para sempre) e o
card travado — e POST /answer exige PAUSED, entao nem a retomada manual funciona.
O sweep marca a Execution como PAUSED, move o card para `paused` (se a transicao
permitir) e comenta no card para o humano retomar pela aba Interacao.
"""

import traceback
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
    """Marca como PAUSED toda Execution RUNNING ativa (orfa de restart). Devolve o total.

    Filtra `is_active`: orfa REAL de crash fica RUNNING+is_active=True (nada desativa com o
    servidor caido). Rows RUNNING+is_active=False sao residuos de crashes antigos ja
    superados por um run posterior — recupera-las puxaria cards concluidos de volta p/ paused.

    O sweep NUNCA derruba o boot: qualquer excecao e logada e a funcao devolve 0.
    """
    try:
        async with session_maker() as s:
            rows = (await s.execute(
                select(Execution).where(
                    Execution.status == ExecutionStatus.RUNNING,
                    Execution.is_active == True,  # noqa: E712
                )
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
                if card:
                    if card.column_id != "paused":
                        moved, err = await repo.move(ex.card_id, "paused")
                        if err:
                            print(
                                f"[recovery] card {ex.card_id}: nao movido para paused ({err}) "
                                "— Execution pausada mesmo assim"
                            )
                    # Sem try/except aqui de proposito: engolir o erro deixaria a
                    # sessao envenenada (PendingRollbackError no commit). Falha de
                    # comentario e coberta pelo guard externo (sweep best-effort).
                    await ActivityRepository(s).add_comment(ex.card_id, "agent", _RESUME_HINT)
            await s.commit()
            return len(rows)
    except Exception:  # noqa: BLE001 — recovery nunca pode impedir o servidor de subir
        print(f"[recovery] sweep de executions orfas falhou:\n{traceback.format_exc()}")
        return 0
