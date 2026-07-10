"""Semeia o workflow 'dev' default (idempotente)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.workflow import Workflow

DEV_WORKFLOW_ID = "dev"

# Coluna: key, label, agentKey (None = manual/backend), provider, model, flags
# 'paused' e a PRIMEIRA coluna do board: cards aguardando humano ficam visiveis sem scroll.
DEV_COLUMNS = [
    {"key": "paused", "label": "Paused", "order": 0, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": True, "isTerminal": False},
    {"key": "backlog", "label": "Backlog", "order": 1, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "plan", "label": "Plan", "order": 2, "agentKey": "plan",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "implement", "label": "Implement", "order": 3, "agentKey": "implement",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "review", "label": "Review", "order": 4, "agentKey": "review",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "validate_ci", "label": "Validate/CI", "order": 5, "agentKey": "validate-ci",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "ready_to_merge", "label": "Ready to merge", "order": 6, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "done", "label": "Done", "order": 7, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": True},
]

# Caminho feliz + fix-loop (review->implement) + pausa a partir de qualquer etapa ativa.
DEV_TRANSITIONS = {
    "backlog": ["plan", "paused"],
    "plan": ["implement", "paused"],
    "implement": ["review", "paused"],
    "review": ["validate_ci", "implement", "paused"],
    "validate_ci": ["ready_to_merge", "implement", "paused"],
    "ready_to_merge": ["done", "paused"],
    "done": [],
    "paused": ["plan", "implement", "review", "validate_ci", "ready_to_merge"],
}


async def seed_dev_workflow(session: AsyncSession) -> None:
    """Cria OU atualiza o workflow dev (config-as-code: o seed e a fonte de verdade;
    nao ha CRUD de workflow, entao mudancas de config chegam ao DB por aqui)."""
    existing = (await session.execute(
        select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID)
    )).scalar_one_or_none()
    if existing is None:
        session.add(Workflow(
            id=DEV_WORKFLOW_ID,
            name="Desenvolvimento (DevKit)",
            columns=DEV_COLUMNS,
            transitions=DEV_TRANSITIONS,
        ))
    else:
        existing.columns = DEV_COLUMNS
        existing.transitions = DEV_TRANSITIONS
    await session.commit()
