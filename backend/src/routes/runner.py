"""Rota do runner (Fase 3b): dispara o pipeline orquestrado e consulta o run."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.execution import Execution, ExecutionLog
from ..models.project_registry import Project
from ..repositories.card_repository import CardRepository
from ..services.pipeline_service import create_execution, run_pipeline

router = APIRouter(prefix="/api/projects/{project_id}/cards", tags=["runner"])


@router.post("/{card_id}/execute")
async def execute_card(project_id: str, card_id: str, db: AsyncSession = Depends(get_db)):
    """Dispara o pipeline em background e retorna na hora com o executionId."""
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = CardRepository(db)
    card = await repo.get_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    execution_id = await create_execution(db, card_id, card.title)

    # roda o pipeline em background (abre a propria sessao); nao bloqueia o request
    asyncio.create_task(run_pipeline(project_id, card_id, execution_id=execution_id))

    return {"success": True, "executionId": execution_id, "cardId": card_id}


@router.get("/{card_id}/execution")
async def get_card_execution(project_id: str, card_id: str, db: AsyncSession = Depends(get_db)):
    """Ultimo run do card + seus logs (para reload/historico do painel)."""
    execution = (await db.execute(
        select(Execution).where(Execution.card_id == card_id)
        .order_by(Execution.started_at.desc())
    )).scalars().first()
    if not execution:
        return {"execution": None, "logs": []}

    logs = (await db.execute(
        select(ExecutionLog).where(ExecutionLog.execution_id == execution.id)
        .order_by(ExecutionLog.sequence)
    )).scalars().all()

    return {
        "execution": {
            "id": execution.id,
            "status": execution.status.value if execution.status else None,
            "workflowStage": execution.workflow_stage,
            "workflowError": execution.workflow_error,
            "costUsd": float(execution.execution_cost) if execution.execution_cost else None,
            "isActive": execution.is_active,
            "startedAt": execution.started_at.isoformat() if execution.started_at else None,
            "completedAt": execution.completed_at.isoformat() if execution.completed_at else None,
        },
        "logs": [
            {"type": lg.type, "content": lg.content, "sequence": lg.sequence}
            for lg in logs
        ],
    }
