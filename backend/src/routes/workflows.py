"""Rotas de leitura da config de workflow (tabela Workflow)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.workflow import Workflow

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": {
        "id": wf.id, "name": wf.name,
        "columns": wf.columns, "transitions": wf.transitions,
    }}
