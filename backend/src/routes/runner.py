"""Rota do runner (Fase 3b): executa um card numa worktree do projeto."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.card import Card
from ..models.project_registry import Project
from ..repositories.card_repository import CardRepository
from ..schemas.card import CardUpdate
from ..services.runner_service import run_card

router = APIRouter(prefix="/api/projects/{project_id}/cards", tags=["runner"])


@router.post("/{card_id}/execute")
async def execute_card(project_id: str, card_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = CardRepository(db)
    card = await repo.get_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    result = await run_card(
        title=card.title, description=card.description or "",
        project_path=project.path, base_branch=project.base_branch, card_id=card.id,
    )
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "runner failed")

    # persistir worktree/branch no card
    await repo.update(card.id, CardUpdate(branch_name=result.branch_name, worktree_path=result.worktree_path))
    await db.commit()

    return {
        "success": True,
        "worktreePath": result.worktree_path,
        "branchName": result.branch_name,
        "resultText": result.result_text,
        "costUsd": result.cost_usd,
        "logsCount": len(result.logs),
    }
