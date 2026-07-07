"""Modelos de métricas para análise de desempenho e custos."""

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Date, Text, JSON, BigInteger, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from ..database import Base


class ProjectMetrics(Base):
    """Métricas agregadas por projeto."""

    __tablename__ = "project_metrics"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)

    # Métricas de Tokens
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # Métricas de Tempo
    avg_execution_time_ms = Column(Integer)  # Tempo médio em ms
    min_execution_time_ms = Column(Integer)
    max_execution_time_ms = Column(Integer)
    total_execution_time_ms = Column(BigInteger)

    # Métricas de Custo
    total_cost_usd = Column(Numeric(10, 6))
    cost_by_model = Column(JSON)  # {"opus-4.5": 12.50, "sonnet-4.5": 8.30}

    # Métricas de Produtividade
    cards_completed = Column(Integer, default=0)
    cards_in_progress = Column(Integer, default=0)
    success_rate = Column(Float)  # Percentual de execuções bem-sucedidas

    # Agregações Temporais
    metrics_date = Column(Date)
    metrics_hour = Column(Integer)  # 0-23 para agregação por hora

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def to_dict(self):
        """Converte o modelo para um dicionário."""
        return {
            "id": self.id,
            "projectId": self.project_id,
            "totalInputTokens": self.total_input_tokens,
            "totalOutputTokens": self.total_output_tokens,
            "totalTokens": self.total_tokens,
            "avgExecutionTimeMs": self.avg_execution_time_ms,
            "minExecutionTimeMs": self.min_execution_time_ms,
            "maxExecutionTimeMs": self.max_execution_time_ms,
            "totalExecutionTimeMs": self.total_execution_time_ms,
            "totalCostUsd": float(self.total_cost_usd) if self.total_cost_usd else 0,
            "costByModel": self.cost_by_model or {},
            "cardsCompleted": self.cards_completed,
            "cardsInProgress": self.cards_in_progress,
            "successRate": self.success_rate,
            "metricsDate": self.metrics_date.isoformat() if self.metrics_date else None,
            "metricsHour": self.metrics_hour,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class ExecutionMetrics(Base):
    """Métricas detalhadas por execução."""

    __tablename__ = "execution_metrics"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = Column(String, ForeignKey("executions.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)

    # Detalhes da Execução
    command = Column(String)  # /plan, /implement, /test, /review
    model_used = Column(String)

    # Métricas de Tempo
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)  # Duração em milissegundos

    # Métricas de Tokens
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    total_tokens = Column(Integer)

    # Métricas de Custo
    estimated_cost_usd = Column(Numeric(10, 6))

    # Status
    status = Column(String)  # success, error, cancelled
    error_message = Column(Text, nullable=True)

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    execution = relationship("Execution", foreign_keys=[execution_id])
    card = relationship("Card", foreign_keys=[card_id])

    def to_dict(self):
        """Converte o modelo para um dicionário."""
        return {
            "id": self.id,
            "executionId": self.execution_id,
            "cardId": self.card_id,
            "projectId": self.project_id,
            "command": self.command,
            "modelUsed": self.model_used,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "durationMs": self.duration_ms,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "estimatedCostUsd": float(self.estimated_cost_usd) if self.estimated_cost_usd else 0,
            "status": self.status,
            "errorMessage": self.error_message,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
