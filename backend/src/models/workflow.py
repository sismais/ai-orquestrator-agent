"""Workflow como config (colunas + transicoes). Tabela global."""

from datetime import datetime
from typing import Any
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Workflow(Base):
    """Definicao de workflow: colunas (com agente/provider/model) + transicoes."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # columns: list[{key,label,order,agentKey|None,provider,model|None,isPausedState,isTerminal}]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # transitions: {fromKey: [toKey, ...]}
    transitions: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Workflow(id={self.id}, name={self.name})>"
