"""Registro (catalogo) de projetos-alvo. Tabela global (sem project_id)."""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Project(Base):
    """Projeto registrado no orquestrador (um repo-alvo)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    remote: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rules_file: Mapped[str] = mapped_column(String(120), nullable=False, default="AGENTS.md")
    validate_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name}, path={self.path})>"
