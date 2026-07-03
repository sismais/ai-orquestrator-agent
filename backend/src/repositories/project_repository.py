"""Repository para o registro de projetos (tabela Project)."""

from uuid import uuid4
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.project_registry import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Project]:
        result = await self.session.execute(
            select(Project).order_by(Project.favorite.desc(), Project.last_opened_at.desc().nullslast())
        )
        return list(result.scalars().all())

    async def get_by_id(self, project_id: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.path == path))
        return result.scalar_one_or_none()

    async def create(self, name: str, path: str, workflow_id: str | None = "dev",
                     remote: str | None = None, rules_file: str = "AGENTS.md",
                     validate_command: str | None = None, base_branch: str = "main") -> Project:
        project = Project(
            id=str(uuid4()), name=name, path=path, remote=remote,
            rules_file=rules_file, validate_command=validate_command,
            base_branch=base_branch, workflow_id=workflow_id,
        )
        self.session.add(project)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def update(self, project_id: str, fields: dict[str, Any]) -> Optional[Project]:
        project = await self.get_by_id(project_id)
        if not project:
            return None
        allowed = {"name", "remote", "rules_file", "validate_command",
                   "base_branch", "workflow_id", "favorite", "last_opened_at"}
        for key, value in fields.items():
            if key in allowed:
                setattr(project, key, value)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: str) -> bool:
        project = await self.get_by_id(project_id)
        if not project:
            return False
        await self.session.delete(project)
        await self.session.flush()
        return True
