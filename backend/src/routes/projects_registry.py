"""Rotas do registro de projetos (catalogo, tabela Project). Aditivo — nao
substitui as rotas legadas /api/projects (load/current/recent)."""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..repositories.project_repository import ProjectRepository

router = APIRouter(prefix="/api/registry/projects", tags=["projects-registry"])


class ProjectCreateBody(BaseModel):
    name: str
    path: str
    remote: Optional[str] = None
    rules_file: str = Field("AGENTS.md", alias="rulesFile")
    validate_command: Optional[str] = Field(None, alias="validateCommand")
    base_branch: str = Field("main", alias="baseBranch")
    workflow_id: Optional[str] = Field("dev", alias="workflowId")
    objective: Optional[str] = None

    class Config:
        populate_by_name = True


class ProjectPatchBody(BaseModel):
    name: Optional[str] = None
    remote: Optional[str] = None
    rules_file: Optional[str] = Field(None, alias="rulesFile")
    validate_command: Optional[str] = Field(None, alias="validateCommand")
    base_branch: Optional[str] = Field(None, alias="baseBranch")
    workflow_id: Optional[str] = Field(None, alias="workflowId")
    favorite: Optional[bool] = None
    objective: Optional[str] = None

    class Config:
        populate_by_name = True


def _to_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "path": p.path, "remote": p.remote,
        "rulesFile": p.rules_file, "validateCommand": p.validate_command,
        "baseBranch": p.base_branch, "workflowId": p.workflow_id,
        "favorite": p.favorite, "objective": p.objective,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
        "lastOpenedAt": p.last_opened_at.isoformat() if p.last_opened_at else None,
    }


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    return {"projects": [_to_dict(p) for p in await repo.list()]}


@router.post("", status_code=201)
async def create_project(body: ProjectCreateBody, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    if await repo.get_by_path(body.path):
        raise HTTPException(status_code=409, detail="Project with this path already registered")
    p = await repo.create(
        name=body.name, path=body.path, remote=body.remote, rules_file=body.rules_file,
        validate_command=body.validate_command, base_branch=body.base_branch,
        workflow_id=body.workflow_id, objective=body.objective,
    )
    await db.commit()
    return {"project": _to_dict(p)}


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    p = await repo.get_by_id(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": _to_dict(p)}


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatchBody, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    p = await repo.update(project_id, body.model_dump(exclude_unset=True, by_alias=False))
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return {"project": _to_dict(p)}


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    if not await repo.delete(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return {"success": True}
