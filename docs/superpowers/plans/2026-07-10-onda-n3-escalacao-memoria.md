# Onda N3 — Gate de escalação (clarifier) + memória de decisões — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Antes de pausar por `pendingQuestions` de um estágio de planejamento, um **agente revisor de escalação** (o clarifier do DevKit, com contexto limpo) julga cada dúvida com o score 0–3 do Pause-or-Decide, consultando as **decisões anteriores do projeto**: o que tiver base decidida (score ≥ 2, com fontes) é respondido automaticamente e o estágio re-roda com as decisões; só o genuinamente ambíguo chega ao humano. Toda decisão — humana ou do clarifier — é **persistida por projeto** (`decisions`) e reinjetada nos prompts de planejamento futuros. Dimensão 3 da revisão estratégica; padrão Anthropic 3 (memória) na versão mínima.

**Architecture:** Tabela nova `Decision` (project-scoped; `create_all` cria — sem light migration, que é só para colunas novas). `POST /answer` grava a resposta humana como Decision (pareada com a última pergunta do agente no card). No pipeline, o gate roda SÓ para `pendingQuestions` de estágios de planejamento (branch genérico — plan/specify/clarify/tasks); `needs_human` do implement NÃO passa pelo gate (conservador por design: ações destrutivas/decisões de produto ficam com o humano — mitigação prevista na spec). O gate é 1 despacho de `stage_fn("clarify", ...)` com prompt custom (perguntas + decisões passadas + regras de score); se TODAS as perguntas forem decididas, o estágio original re-roda UMA vez com as decisões injetadas (mesmo mecanismo do `human_answer`); se sobrar pergunta, pausa só com as restantes. Decisões recentes do projeto entram no prompt dos estágios de planejamento como bloco "Decisões anteriores".

**Estado relevante (pós-N4):** branch genérico do pipeline trata plan/specify/clarify/tasks e pausa em `pendingQuestions` via `_format_questions`; `"clarify"` já está em `STAGE_AGENTS` → `sismais-dev-clarifier.md` (score 0–3 documentado no .md); `stage_fn(agent_key, worktree, prompt, ...)` aceita prompt custom; `stage_context` tem project_name/objective/rules_file/requested_by; `account(res, alias)`; `pause_col`/`pause_cols` por config.

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes em `test_test_result_analyzer.py` — ignorar). Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: tabela `Decision` + repositório + registro da resposta humana

**Files:**
- Create: `backend/src/models/decision.py`
- Modify: `backend/src/models/__init__.py` (registrar o model)
- Create: `backend/src/repositories/decision_repository.py`
- Modify: `backend/src/routes/runner.py` (`/answer` grava Decision)
- Test: `backend/tests/test_decisions.py`

- [ ] **Step 1.1: Write the failing tests** — criar `backend/tests/test_decisions.py`:

```python
import pytest
import src.models  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.repositories.decision_repository import DecisionRepository


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def test_add_e_recent_for_project(maker):
    async with maker() as s:
        repo = DecisionRepository(s)
        await repo.add(project_id="p1", card_id="c1", question="Qual banco?",
                       decision="SQLite unico", source="human", stage="plan")
        await repo.add(project_id="p1", card_id="c2", question="Qual auth?",
                       decision="Sem auth (single-user)", source="clarifier", score=2,
                       sources=["AGENTS.md"], stage="specify")
        await repo.add(project_id="OUTRO", card_id="c3", question="X?",
                       decision="Y", source="human", stage="plan")
        await s.commit()

        rows = await repo.recent_for_project("p1", limit=10)
        assert len(rows) == 2                      # escopado por projeto
        assert rows[0].question == "Qual auth?"    # mais recente primeiro
        assert rows[0].score == 2
        assert rows[0].sources == ["AGENTS.md"]


async def test_format_decisions_block(maker):
    from src.repositories.decision_repository import format_decisions_block
    async with maker() as s:
        repo = DecisionRepository(s)
        await repo.add(project_id="p1", card_id="c1", question="Qual banco?",
                       decision="SQLite unico", source="human", stage="plan")
        await s.commit()
        rows = await repo.recent_for_project("p1")
    block = format_decisions_block(rows)
    assert "Qual banco?" in block
    assert "SQLite unico" in block
    assert format_decisions_block([]) == ""
```

- [ ] **Step 1.2:** Rodar — Expected: FAIL (módulos inexistentes).

- [ ] **Step 1.3: Model** — criar `backend/src/models/decision.py`:

```python
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
```

Em `backend/src/models/__init__.py`, adicionar `from .decision import Decision` (siga o padrão do arquivo).

- [ ] **Step 1.4: Repositório** — criar `backend/src/repositories/decision_repository.py`:

```python
"""Repositorio da memoria de decisoes (N3). Flush sem commit (quem chama commita)."""

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.decision import Decision


class DecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, project_id: str, question: str, decision: str, source: str,
                  card_id: Optional[str] = None, score: Optional[int] = None,
                  sources: Optional[list] = None, stage: Optional[str] = None) -> Decision:
        row = Decision(project_id=project_id, card_id=card_id, question=question,
                       decision=decision, source=source, score=score, sources=sources,
                       stage=stage)
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent_for_project(self, project_id: str, limit: int = 10) -> list:
        rows = (await self.session.execute(
            select(Decision).where(Decision.project_id == project_id)
            .order_by(desc(Decision.created_at), desc(Decision.id)).limit(limit)
        )).scalars().all()
        return list(rows)


def format_decisions_block(rows: list) -> str:
    """Bloco de prompt com as decisoes anteriores ('' se vazio)."""
    if not rows:
        return ""
    lines = ["Decisoes anteriores deste projeto (respeite-as; NAO re-pergunte o que ja foi decidido):"]
    for r in rows:
        src = f" [fontes: {', '.join(r.sources)}]" if r.sources else ""
        lines.append(f"- P: {r.question}\n  D: {r.decision} ({r.source}{src})")
    return "\n".join(lines)
```

- [ ] **Step 1.5: `/answer` grava a Decision** — em `backend/src/routes/runner.py`, no `answer_card`, após o `add_comment(card_id, "human", message)`: buscar a última pergunta do agente (último comentário `agent` do card) e gravar a Decision:

```python
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
```

(posicione ANTES do `asyncio.create_task(...)`; `select` já é importado no arquivo.)

Teste adicional em `backend/tests/test_decisions.py` (rota, padrão httpx/ASGITransport — siga `test_projects_registry_routes.py`): pausar não é preciso simular por completo; alternativa mais simples: teste de integração leve chamando a função interna? Se o padrão de rota do repo exigir muito setup (Execution PAUSED + card + projeto), monte-o como os testes de `/answer` existentes fazem — procure por testes que exercitam `/answer` (`grep -rn "answer" backend/tests/`); se NÃO existir teste de rota do /answer, escreva o teste no nível do repositório apenas (o wiring da rota é coberto pelo teste manual do fluxo) e documente no report.

- [ ] **Step 1.6:** `pytest tests/test_decisions.py -v` — PASS. Suíte completa sem regressão.

- [ ] **Step 1.7: Commit**

```bash
git add backend/src/models/decision.py backend/src/models/__init__.py backend/src/repositories/decision_repository.py backend/src/routes/runner.py backend/tests/test_decisions.py
git commit -m "feat(memoria): tabela decisions por projeto + resposta humana do /answer registrada (N3)"
```

---

### Task 2: decisões anteriores no prompt dos estágios de planejamento

**Files:**
- Modify: `backend/src/services/stage_runner.py` (`build_stage_prompt`: bloco decisions nos branches plan e genérico)
- Modify: `backend/src/services/pipeline_service.py` (carregar decisões e passar em `extra`)
- Test: `backend/tests/test_stage_runner_load.py`, `backend/tests/test_pipeline_service.py`

- [ ] **Step 2.1: Write the failing tests**

Em `backend/tests/test_stage_runner_load.py`:

```python
def test_prompt_de_planejamento_inclui_decisoes_anteriores():
    from src.services.stage_runner import build_stage_prompt
    extra = {"decisions": "Decisoes anteriores deste projeto...\n- P: Qual banco?\n  D: SQLite"}
    for stage in ("plan", "specify"):
        p = build_stage_prompt(stage, "T", "D", "/wt", extra)
        assert "Qual banco?" in p, stage
    # implement/review NAO recebem o bloco (foco: planejamento)
    for stage in ("implement", "review"):
        p = build_stage_prompt(stage, "T", "D", "/wt", extra)
        assert "Qual banco?" not in p, stage
```

Em `backend/tests/test_pipeline_service.py`:

```python
async def test_decisoes_anteriores_chegam_ao_prompt_do_plan(maker):
    """N3: decisoes de cards passados do MESMO projeto entram no prompt de planejamento."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        from src.repositories.decision_repository import DecisionRepository
        await DecisionRepository(s).add(project_id="p1", card_id="outro-card",
                                        question="Qual ORM?", decision="SQLAlchemy 2 async",
                                        source="human", stage="plan")
        await s.commit()

    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert "SQLAlchemy 2 async" in seen["plan"][0]
    assert "SQLAlchemy 2 async" not in seen["implement"][0]
```

- [ ] **Step 2.2:** Rodar — Expected: FAIL.

- [ ] **Step 2.3: Implementar**

1. `stage_runner.build_stage_prompt`: definir uma vez, junto do `answer_block`:

```python
    decisions = extra.get("decisions")
    decisions_block = f"\n\n{decisions}\n" if decisions else ""
```

e incluir `{decisions_block}` nos prompts do branch `plan` e do branch genérico (logo após `{answer_block}`). NÃO incluir em implement/review/ci-triage/triage.

2. `pipeline_service.run_pipeline`: junto do carregamento do workflow (antes do laço), carregar as decisões UMA vez:

```python
        from ..repositories.decision_repository import DecisionRepository, format_decisions_block
        decisions_block = format_decisions_block(
            await DecisionRepository(s).recent_for_project(project_id, limit=10)
        )
```

(import no topo do arquivo, não inline — siga o padrão dos imports existentes.) No laço, ao montar `extra` para estágios de planejamento (branch genérico e quando `agent_key == "plan"`): `if decisions_block and agent_key not in ("implement", "review"): extra["decisions"] = decisions_block`. Como o `extra` é montado antes do dispatch, aplique a condição pelo `agent_key` corrente.

- [ ] **Step 2.4:** `pytest tests/test_stage_runner_load.py tests/test_pipeline_service.py -v` — PASS (o teste de contexto do projeto e demais continuam verdes: o bloco só entra quando há decisões).

- [ ] **Step 2.5: Commit**

```bash
git add backend/src/services/stage_runner.py backend/src/services/pipeline_service.py backend/tests/test_stage_runner_load.py backend/tests/test_pipeline_service.py
git commit -m "feat(memoria): decisoes anteriores do projeto reinjetadas nos prompts de planejamento (N3)"
```

---

### Task 3: gate de escalação — clarifier julga antes de pausar

**Files:**
- Modify: `backend/src/services/findings.py` (`parse_clarifier_output`)
- Modify: `backend/src/services/pipeline_service.py` (gate no branch genérico)
- Test: `backend/tests/test_findings.py`, `backend/tests/test_pipeline_service.py`

- [ ] **Step 3.1: Write the failing tests**

Em `backend/tests/test_findings.py`:

```python
def test_parse_clarifier_output():
    from src.services.findings import parse_clarifier_output
    out = parse_clarifier_output(
        'analise...\n{"decisions": [{"question": "Qual banco?", "decision": "SQLite", '
        '"score": 2, "sources": ["AGENTS.md"]}], "pendingQuestions": []}'
    )
    assert out["decisions"][0]["decision"] == "SQLite"
    assert out["pendingQuestions"] == []
    # sem JSON -> nada decidido, tudo pendente (fail-closed do gate)
    vazio = parse_clarifier_output("nao sei")
    assert vazio["decisions"] == [] and vazio["pendingQuestions"] == []
```

Em `backend/tests/test_pipeline_service.py`:

```python
async def test_gate_resolve_pendencias_e_estagio_re_roda(maker):
    """N3: clarifier decide (score>=2) -> plan re-roda com as decisoes, sem pausar."""
    card_id = await _make_project_card(maker)
    calls = {"plan": 0}
    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        if stage_key == "plan":
            calls["plan"] += 1
            if calls["plan"] == 1:
                return StageResult(ok=True, text='{"pendingQuestions":[{"question":"Qual banco?"}]}')
            return StageResult(ok=True, text="plano final ok")
        if stage_key == "clarify":
            return StageResult(ok=True, text=(
                '{"decisions": [{"question": "Qual banco?", "decision": "SQLite unico", '
                '"score": 2, "sources": ["AGENTS.md"]}], "pendingQuestions": []}'
            ))
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"   # NAO pausou
    assert calls["plan"] == 2                                        # re-rodou com as decisoes
    assert "SQLite unico" in seen["plan"][1]                         # decisao injetada no re-run
    # decisao do clarifier persistida na memoria
    async with maker() as s:
        from src.repositories.decision_repository import DecisionRepository
        rows = await DecisionRepository(s).recent_for_project("p1")
    assert any(r.source == "clarifier" and "SQLite" in r.decision for r in rows)


async def test_gate_com_pendencia_restante_pausa_so_com_ela(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "plan":
            return StageResult(ok=True, text=(
                '{"pendingQuestions":[{"question":"Qual banco?"},{"question":"Qual cor do botao?"}]}'
            ))
        if stage_key == "clarify":
            return StageResult(ok=True, text=(
                '{"decisions": [{"question": "Qual banco?", "decision": "SQLite", "score": 2, '
                '"sources": ["AGENTS.md"]}], '
                '"pendingQuestions": [{"question": "Qual cor do botao?"}]}'
            ))
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    # a pausa carrega SO a pergunta restante (a decidida nao volta ao humano)
    async with maker() as s:
        from sqlalchemy import select as _sel
        from src.models.activity_log import ActivityLog, ActivityType
        acts = (await s.execute(_sel(ActivityLog).where(
            ActivityLog.card_id == card_id,
            ActivityLog.activity_type == ActivityType.COMMENTED,
        ))).scalars().all()
    agent_comments = [a.description or "" for a in acts if a.user_id == "agent"]
    assert any("Qual cor do botao?" in c for c in agent_comments)
    assert not any("Qual banco?" in c for c in agent_comments)


async def test_gate_com_clarifier_quebrado_pausa_com_tudo(maker):
    """Fail-closed: clarifier com erro/lixo -> pausa com TODAS as perguntas originais."""
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "plan":
            return StageResult(ok=True, text='{"pendingQuestions":[{"question":"Qual banco?"}]}')
        if stage_key == "clarify":
            return StageResult(ok=False, error="explodiu")
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
```

NOTA: `test_pending_questions_on_plan_pauses` (existente) tem plan devolvendo pendingQuestions e o fake devolvendo `"clarify ok"` para o clarify (não-scriptado) → parse fail-closed → pausa com tudo → o teste continua verde. CONFIRME.

- [ ] **Step 3.2:** Rodar — Expected: FAIL.

- [ ] **Step 3.3: Parser** — em `backend/src/services/findings.py`:

```python
def parse_clarifier_output(text: str) -> dict:
    """Extrai {decisions, pendingQuestions} do clarifier (gate de escalacao, N3).

    Fail-closed: sem JSON parseavel -> nada decidido ({} vazios) e o chamador pausa
    com as perguntas originais."""
    empty = {"decisions": [], "pendingQuestions": []}
    if not text:
        return dict(empty)
    obj = _last_matching(text, lambda o: "decisions" in o or "pendingQuestions" in o)
    if obj is None:
        return dict(empty)
    return {
        "decisions": _as_list(obj.get("decisions")),
        "pendingQuestions": _as_list(obj.get("pendingQuestions")),
    }
```

- [ ] **Step 3.4: Gate no pipeline** — em `backend/src/services/pipeline_service.py`:

1. Import `parse_clarifier_output` junto dos demais de findings.
2. No branch genérico do laço (onde hoje: `pend = parse_pending_questions(res.text); if pend: finish_pause(...)`), substituir o `if pend:` por:

```python
                if pend:
                    # Gate de escalacao (N3): clarifier julga com score 0-3 + decisoes passadas
                    # antes de acionar o humano. Fail-closed: erro/lixo -> pausa com tudo.
                    await log.event(f"── gate de escalacao: {len(pend)} pendencia(s) ──")
                    gate_prompt = (
                        f"Voce e o revisor de escalacao. Um estagio de planejamento ({agent_key}) "
                        f"levantou as pendencias abaixo para a tarefa: {card.title}.\n\n"
                        f"Pendencias:\n{_format_questions(pend)}\n\n"
                        + (f"{decisions_block}\n\n" if decisions_block else "")
                        + "Aplique o Pause-or-Decide (score 0-3, +1 por fonte verificavel entre "
                        "arquivo de regras do projeto, docs/, codigo existente e skills): score >= 2 "
                        "DECIDE citando as fontes; score < 2 mantem a pergunta pendente. "
                        'Devolva SO o JSON {"decisions": [{"question","decision","score","sources"}], '
                        '"pendingQuestions": [{"question","context"}]} — sem prosa fora dele.'
                    )
                    gate = await stage_fn("clarify", worktree, gate_prompt, card_id=card_id,
                                          on_log=log, model=stage_model_for_agent("clarify", card))
                    await log.flush()
                    await account(gate, stage_model_for_agent("clarify", card))
                    if gate.interrupted:
                        await finish_pause("interrompido pelo usuario",
                                           "O usuario parou a execucao durante o gate de escalacao.",
                                           question="Você interrompeu o agente. O que devo ajustar?")
                        return
                    verdict = parse_clarifier_output(gate.text if gate.ok else "")
                    decided = verdict["decisions"]
                    remaining = verdict["pendingQuestions"] if (gate.ok and (decided or verdict["pendingQuestions"])) else pend
                    if decided:
                        try:
                            drepo = DecisionRepository(s)
                            for d in decided:
                                await drepo.add(
                                    project_id=project_id, card_id=card_id,
                                    question=str(d.get("question", ""))[:2000],
                                    decision=str(d.get("decision", ""))[:2000],
                                    source="clarifier", score=d.get("score"),
                                    sources=d.get("sources"), stage=agent_key,
                                )
                            await s.commit()
                        except Exception:  # noqa: BLE001 — memoria best-effort
                            pass
                        await log.event(f"── gate decidiu {len(decided)} pendencia(s) com fonte ──")
                    if remaining:
                        await finish_pause(f"{agent_key}: pendencias", res.text[:1500],
                                           question=_format_questions(remaining))
                        return
                    # tudo decidido: re-roda o estagio UMA vez com as decisoes (mesmo canal do human_answer)
                    decided_text = "\n".join(
                        f"- {d.get('question')}: {d.get('decision')} (fontes: {', '.join(d.get('sources') or [])})"
                        for d in decided
                    )
                    rerun_extra = dict(extra)
                    rerun_extra["human_answer"] = (
                        "Decisoes do revisor de escalacao (com fontes do projeto) — siga-as:\n" + decided_text
                    )
                    rerun_prompt = build_stage_prompt(agent_key, card.title, card.description or "",
                                                      worktree, rerun_extra)
                    res = await stage_fn(agent_key, worktree, rerun_prompt, card_id=card_id,
                                         on_log=log, model=stage_model_for_agent(agent_key, card))
                    await log.flush()
                    await account(res, stage_model_for_agent(agent_key, card))
                    if res.interrupted:
                        await finish_pause("interrompido pelo usuario",
                                           "O usuario parou a execucao.",
                                           question="Você interrompeu o agente. O que devo ajustar?")
                        return
                    if not res.ok:
                        await finish_pause(f"erro no re-run do {agent_key}", res.error)
                        return
                    if not (res.text or "").strip():
                        await finish_pause(f"estagio {agent_key} terminou sem output no re-run",
                                           "O agente encerrou o turno sem produzir texto.")
                        return
                    pend2 = parse_pending_questions(res.text)
                    if pend2:
                        # re-run ainda com pendencias: pausa direto (gate nao roda em loop)
                        await finish_pause(f"{agent_key}: pendencias apos o gate", res.text[:1500],
                                           question=_format_questions(pend2))
                        return
```

(após esse bloco, o fluxo existente segue: `detect_needs_human` sobre o `res` corrente, acúmulo em `chain_parts`, `next_active_column` — CONFIRME que o `res` re-atribuído flui para o restante do branch sem duplicação.)

3. Import `DecisionRepository` no topo do arquivo (junto de `ActivityRepository`).
4. NOTA sobre `_STAGE_MODEL_FIELD`: `"clarify"` já mapeia para `model_plan` (N4) — o gate roda no modelo de planejamento do card. CONFIRME.

- [ ] **Step 3.5:** `pytest tests/test_findings.py tests/test_pipeline_service.py -v` — PASS em todos, incluindo `test_pending_questions_on_plan_pauses` (fail-closed preserva o comportamento com clarifier não-scriptado). Suíte completa (`| tail -3`).

- [ ] **Step 3.6: Commit**

```bash
git add backend/src/services/findings.py backend/src/services/pipeline_service.py backend/tests/test_findings.py backend/tests/test_pipeline_service.py
git commit -m "feat(escalacao): gate do clarifier decide pendencias com fonte antes de pausar; so o ambiguo chega ao humano (N3)"
```

---

### Task 4: API de decisões + suite + docs

**Files:**
- Modify: `backend/src/routes/projects_registry.py` (GET decisions)
- Modify: `docs/ARQUITETURA_E_ESTADO.md`
- Test: `backend/tests/test_decisions.py`

- [ ] **Step 4.1:** Teste (padrão httpx do arquivo de rotas): `GET /api/registry/projects/{pid}/decisions` devolve as decisões do projeto (mais recentes primeiro, campos question/decision/source/score/sources/stage/createdAt). RED → implementar a rota em `projects_registry.py`:

```python
@router.get("/{project_id}/decisions")
async def list_decisions(project_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    from ..repositories.decision_repository import DecisionRepository
    rows = await DecisionRepository(db).recent_for_project(project_id, limit=min(limit, 200))
    return {"decisions": [
        {"id": r.id, "cardId": r.card_id, "question": r.question, "decision": r.decision,
         "source": r.source, "score": r.score, "sources": r.sources, "stage": r.stage,
         "createdAt": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]}
```

→ GREEN.

- [ ] **Step 4.2:** Suíte completa backend + tsc front (baselines). Seção no `docs/ARQUITETURA_E_ESTADO.md` após a N4:

```markdown
### Onda N3 — gate de escalação + memória de decisões — feito 2026-07-10
- Tabela **`decisions`** por projeto (pergunta→decisão, `human`|`clarifier`, score/fontes/etapa);
  resposta humana do `/answer` vira Decision automaticamente; `GET /api/registry/projects/{pid}/decisions`.
- **Gate de escalação:** `pendingQuestions` de estágios de planejamento passam pelo clarifier
  (score 0–3 do Pause-or-Decide + decisões passadas) ANTES de pausar: decidido com fonte → o
  estágio re-roda 1x com as decisões (canal do human_answer) e a decisão é persistida; só o
  restante chega ao humano. Fail-closed: clarifier com erro/lixo → pausa com tudo. `needs_human`
  do implement NÃO passa pelo gate (conservador por design).
- **Decisões reinjetadas:** bloco "Decisões anteriores" nos prompts de planejamento (plan + genéricos).
- Plano: `plans/2026-07-10-onda-n3-escalacao-memoria.md`.
```

- [ ] **Step 4.3: Commit**

```bash
git add backend/src/routes/projects_registry.py backend/tests/test_decisions.py docs/ARQUITETURA_E_ESTADO.md
git commit -m "feat(memoria): API de decisoes por projeto + docs da onda N3"
```

## Self-review (feito na escrita)

- Fail-closed em todas as bordas do gate: clarifier `ok=False`/lixo/vazio → `remaining = pend` (pausa com tudo — comportamento pré-N3); re-run com pendências → pausa direto (sem loop de gate); interrupted em qualquer despacho → pausa de interrupt.
- Custo: no pior caso o gate adiciona 1 turno de clarifier + 1 re-run do estágio — ambos contabilizados via `account`.
- `test_pending_questions_on_plan_pauses` existente permanece válido (clarifier não-scriptado → "clarify ok" → parse fail-closed → pausa).
- A tabela nova dispensa light migration (create_all); `models/__init__.py` registra para o `Base.metadata` dos testes.
