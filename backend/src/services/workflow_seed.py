"""Semeia o workflow 'dev' default (idempotente)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.workflow import Workflow

DEV_WORKFLOW_ID = "dev"

# Coluna: key, label, agentKey (None = manual/backend), provider, model, flags
DEV_COLUMNS = [
    {"key": "backlog", "label": "Backlog", "order": 0, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "plan", "label": "Plan", "order": 1, "agentKey": "plan",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "implement", "label": "Implement", "order": 2, "agentKey": "implement",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "review", "label": "Review", "order": 3, "agentKey": "review",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "validate_ci", "label": "Validate/CI", "order": 4, "agentKey": "validate-ci",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "ready_to_merge", "label": "Ready to merge", "order": 5, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "done", "label": "Done", "order": 6, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": True},
    {"key": "paused", "label": "Paused", "order": 7, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": True, "isTerminal": False},
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
    """Cria o workflow dev se ainda nao existir (idempotente)."""
    existing = await session.execute(
        select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID)
    )
    if existing.scalar_one_or_none() is not None:
        return
    session.add(Workflow(
        id=DEV_WORKFLOW_ID,
        name="Desenvolvimento (DevKit)",
        columns=DEV_COLUMNS,
        transitions=DEV_TRANSITIONS,
    ))
    await session.commit()
