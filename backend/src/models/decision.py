"""Memoria de decisoes por projeto (N3): pares pergunta->decisao, humanas ou do clarifier.

Reinjetadas nos prompts de planejamento e consultadas pelo gate de escalacao —
'consultar decisoes semelhantes anteriores' antes de acionar o humano (visao/padrao 3).
"""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from ..database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    card_id = Column(String(36), nullable=True)
    question = Column(Text, nullable=False)
    decision = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)   # 'human' | 'clarifier'
    score = Column(Integer, nullable=True)        # score do Pause-or-Decide (clarifier)
    sources = Column(JSON, nullable=True)         # fontes citadas pelo clarifier
    stage = Column(String(40), nullable=True)     # agentKey/etapa onde surgiu
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
