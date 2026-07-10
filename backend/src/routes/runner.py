"""Rota do runner (Fase 3b): dispara o pipeline orquestrado e consulta o run."""

import asyncio
import traceback

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.execution import Execution, ExecutionLog, ExecutionStatus
from ..models.project_registry import Project
from ..repositories.activity_repository import ActivityRepository
from ..repositories.card_repository import CardRepository
from ..services import session_registry as sessions
from ..services.pipeline_service import create_execution, run_pipeline

router = APIRouter(prefix="/api/projects/{project_id}/cards", tags=["runner"])


def _log_task_result(task: asyncio.Task) -> None:
    """Ultimo recurso: se a task do pipeline morrer com excecao nao tratada, loga em vez de sumir."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        print("[runner] pipeline task morreu com excecao nao tratada:")
        traceback.print_exception(type(exc), exc, exc.__traceback__)


class AnswerRequest(BaseModel):
    message: str


def _resume_stage_from(workflow_stage: str | None) -> str:
    """Etapa de retomada a partir de onde pausou (review nao-convergencia -> implement)."""
    if workflow_stage == "review":
        return "implement"
    return workflow_stage or "plan"


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
    task = asyncio.create_task(run_pipeline(project_id, card_id, execution_id=execution_id))
    task.add_done_callback(_log_task_result)

    return {"success": True, "executionId": execution_id, "cardId": card_id}


@router.post("/{card_id}/answer")
async def answer_card(project_id: str, card_id: str, body: AnswerRequest,
                      db: AsyncSession = Depends(get_db)):
    """Responde a pausa do card (comentario do humano) e RETOMA o pipeline automaticamente."""
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Resposta vazia")

    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = CardRepository(db)
    card = await repo.get_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    last = (await db.execute(
        select(Execution).where(Execution.card_id == card_id).order_by(Execution.started_at.desc())
    )).scalars().first()
    if not last or last.status != ExecutionStatus.PAUSED:
        raise HTTPException(status_code=409, detail="Card nao esta pausado")

    # comentario do humano no thread do card
    await ActivityRepository(db).add_comment(card_id, "human", message)
    # memoria de decisoes (N3): pareia a resposta humana com a ultima pergunta do agente
    try:
        from ..models.activity_log import ActivityLog, ActivityType
        from ..repositories.decision_repository import DecisionRepository
        last_q = (await db.execute(
            select(ActivityLog).where(
                ActivityLog.card_id == card_id,
                ActivityLog.activity_type == ActivityType.COMMENTED,
                ActivityLog.user_id == "agent",
            ).order_by(ActivityLog.timestamp.desc())
        )).scalars().first()
        await DecisionRepository(db).add(
            project_id=project_id, card_id=card_id,
            question=(last_q.description if last_q else "(pergunta nao registrada)")[:2000],
            decision=message[:2000], source="human", stage=last.workflow_stage,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — memoria e best-effort, nunca bloqueia a retomada
        pass
    resume_stage = _resume_stage_from(last.workflow_stage)
    execution_id = await create_execution(db, card_id, card.title)

    task = asyncio.create_task(run_pipeline(
        project_id, card_id, execution_id=execution_id,
        resume_stage=resume_stage, human_answer=message,
    ))
    task.add_done_callback(_log_task_result)
    return {"success": True, "executionId": execution_id, "resumeStage": resume_stage}


@router.post("/{card_id}/stop")
async def stop_card(project_id: str, card_id: str):
    """Interrompe (Stop) o agente da etapa em execucao. O pipeline pausa o card para correcao."""
    ok = await sessions.interrupt(card_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Nenhuma execucao ativa para interromper")
    return {"success": True, "interrupted": True}


@router.post("/{card_id}/say")
async def say_card(project_id: str, card_id: str, body: AnswerRequest, db: AsyncSession = Depends(get_db)):
    """Fala com o agente ao vivo durante a execucao (injeta a mensagem na sessao). Incremento 2."""
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    ok = await sessions.say(card_id, message)
    if not ok:
        raise HTTPException(status_code=409, detail="Nenhuma execucao ativa")
    await ActivityRepository(db).add_comment(card_id, "human", message)
    return {"success": True}


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
            "prUrl": execution.result if (execution.result or "").startswith("http") else None,
            "costUsd": float(execution.execution_cost) if execution.execution_cost else None,
            "fixIterations": execution.fix_iterations,
            "track": execution.track,
            "modelUsed": execution.model_used,
            "totalTokens": execution.total_tokens,
            "isActive": execution.is_active,
            "startedAt": execution.started_at.isoformat() if execution.started_at else None,
            "completedAt": execution.completed_at.isoformat() if execution.completed_at else None,
        },
        "logs": [
            {"type": lg.type, "content": lg.content, "sequence": lg.sequence}
            for lg in logs
        ],
    }
