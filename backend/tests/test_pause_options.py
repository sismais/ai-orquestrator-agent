"""Respostas sugeridas (chips) na pausa do pipeline.

Contrato: pendingQuestions do clarifier/planner podem trazer `options` (2-4 respostas
completas). Com UMA pergunta pendente, as opcoes viram chips no card pausado (via
new_value JSON do comentario do agente); com varias, ficam so no texto numerado.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from src.repositories.activity_repository import ActivityRepository
from src.services.pipeline_service import _format_questions, _pending_options


def test_pending_options_uma_pergunta_com_options():
    pend = [{"question": "Qual fluxo?", "options": ["Usar fluxo A", "Usar fluxo B", "  "]}]
    assert _pending_options(pend) == ["Usar fluxo A", "Usar fluxo B"]


def test_pending_options_limita_a_quatro_e_trunca():
    pend = [{"question": "q", "options": ["a" * 400, "b", "c", "d", "e"]}]
    opts = _pending_options(pend)
    assert len(opts) == 4
    assert opts[0] == "a" * 300


def test_pending_options_varias_perguntas_nao_gera_chips():
    pend = [
        {"question": "q1", "options": ["a"]},
        {"question": "q2", "options": ["b"]},
    ]
    assert _pending_options(pend) is None


def test_pending_options_sem_options_ou_invalido():
    assert _pending_options([{"question": "q"}]) is None
    assert _pending_options([{"question": "q", "options": "nao e lista"}]) is None
    assert _pending_options(["pergunta como string"]) is None
    assert _pending_options([]) is None


def test_format_questions_renderiza_options_no_texto():
    pend = [{"question": "Qual fluxo?", "context": "ctx", "options": ["Fluxo A", "Fluxo B"]}]
    text = _format_questions(pend)
    assert "1. Qual fluxo?" in text
    assert "Opções: 1) Fluxo A · 2) Fluxo B" in text


async def test_add_comment_serializa_options_em_new_value():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    repo = ActivityRepository(session)

    com = await repo.add_comment("card-1", "agent", "Qual fluxo?", options=["Fluxo A", "Fluxo B"])
    assert json.loads(com.new_value) == ["Fluxo A", "Fluxo B"]

    sem = await repo.add_comment("card-1", "agent", "Qual fluxo?")
    assert sem.new_value is None
