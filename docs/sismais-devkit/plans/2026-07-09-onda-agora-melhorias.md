# Onda "Agora" (A1, A2, A3, A5, A6, A4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar os 6 pacotes "Agora" da revisão estratégica (`docs/sismais-devkit/specs/2026-07-09-revisao-estrategica-plataforma.md`): blindar o loop (A1), review falha-fechada + anti-parada-prematura (A2), notificação de pausa (A3), telemetria de autonomia/custo (A5), higiene do chat (A6) e contexto real no prompt (A4).

**Architecture:** Todas as mudanças são incrementais sobre o pipeline existente (`pipeline_service`/`stage_runner`) e sobre o chat (`chat_service`/`agent_chat`), sem tocar no fluxo provado além dos pontos citados. Backend testado com pytest (padrão de `tests/test_pipeline_service.py`: engine SQLite in-memory + `stage_fn` fake + git stubado). Frontend validado com `npx tsc --noEmit` (gate do repo; há ~7 erros pré-existentes `Cannot find namespace 'NodeJS'` — confira que não introduziu novos).

**Tech Stack:** FastAPI + SQLAlchemy 2 async + SQLite (backend), React 18 + TS + Vite (frontend), claude-agent-sdk.

**Regras do repo que este plano respeita:** banco único tenant-shaped; workflow como config; DevKit não injetado na worktree; execução real gasta Max (smoke real só no `spike-loop-test`, e NÃO faz parte deste plano — os testes aqui são unitários); nada é removido fora de item explícito.

**Branch:** `feat/melhorias-by-fable-5` (atual). Commits pequenos por task.

**Como rodar os testes (Windows/Git Bash):**
```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v
cd frontend && npx tsc --noEmit
```
Baseline conhecido: `test_project_manager.py`/`test_test_result_analyzer.py` têm falhas pré-existentes do fork — ignore-as; foque nas suas.

---

### Task 0: Commitar o spec da revisão estratégica

**Files:**
- Commit: `docs/sismais-devkit/specs/2026-07-09-revisao-estrategica-plataforma.md` (untracked)

- [ ] **Step 0.1: Commit**

```bash
git add docs/sismais-devkit/specs/2026-07-09-revisao-estrategica-plataforma.md docs/sismais-devkit/plans/2026-07-09-onda-agora-melhorias.md
git commit -m "docs: revisão estratégica da plataforma + plano da onda Agora"
```

---

### Task 1 (A1a): try/except de topo em `run_pipeline` + done-callback no create_task

Exceção fora do `stage_fn` (ex.: `repo.move`, `commit_all`, `diff_against_base`) hoje mata a task em silêncio e deixa a Execution `RUNNING` órfã. Passa a pausar o card com motivo.

**Files:**
- Modify: `backend/src/services/pipeline_service.py`
- Modify: `backend/src/routes/runner.py`
- Test: `backend/tests/test_pipeline_service.py`

- [ ] **Step 1.1: Write the failing test**

Adicionar ao final de `backend/tests/test_pipeline_service.py`:

```python
async def test_excecao_inesperada_pausa_o_card(maker):
    """Excecao fora do stage_fn nao pode deixar a Execution RUNNING orfa (A1)."""
    card_id = await _make_project_card(maker)

    async def boom(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        raise RuntimeError("explodiu por dentro")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=boom)

    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "paused"
    assert ex.is_active is False
    assert "erro interno" in (ex.workflow_error or "")
```

Nota: `run_stage` real captura exceções e devolve `ok=False`; um `stage_fn` que LEVANTA simula exatamente a classe de exceção "fora do estágio" que hoje escapa.

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py::test_excecao_inesperada_pausa_o_card -v`
Expected: FAIL — `RuntimeError: explodiu por dentro` propaga (nenhum try/except de topo hoje).

- [ ] **Step 1.3: Envolver o corpo de `run_pipeline` em try/except**

Em `backend/src/services/pipeline_service.py`, dentro de `run_pipeline`, envolver TODO o trecho a partir do comentário `# 1) worktree — na retomada reusa a existente...` até o final da função (inclusive o epílogo de sucesso) num `try:`, reindentando o bloco em um nível, e fechar com:

```python
        try:
            # 1) worktree ...
            ...  # (bloco existente, reindentado — do `reuse = bool(...)` até o notify_complete final)
        except Exception as e:  # noqa: BLE001 — rede de seguranca: run orfao nunca mais (A1)
            try:
                await finish_pause("erro interno do orquestrador", str(e))
            except Exception as e2:  # noqa: BLE001 — ultimo recurso: marca a Execution direto
                print(f"[pipeline] finish_pause falhou apos erro interno: {e2!r}")
                execution.status = ExecutionStatus.ERROR
                execution.workflow_error = f"erro interno: {e} | finish_pause: {e2}"[:1900]
                execution.is_active = False
                execution.completed_at = datetime.utcnow()
                await s.commit()
```

Importante: `finish_pause` e `execution` já estão definidos ANTES desse bloco (linhas ~180-227) — a ordem atual do código já permite o wrap. Os `return` internos do bloco continuam funcionando dentro do `try`.

- [ ] **Step 1.4: done-callback nas tasks de background**

Em `backend/src/routes/runner.py`, adicionar após os imports:

```python
def _log_task_result(task: asyncio.Task) -> None:
    """Ultimo recurso: se a task do pipeline morrer com excecao nao tratada, loga em vez de sumir."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        print(f"[runner] pipeline task morreu com excecao nao tratada: {exc!r}")
```

E nos DOIS `asyncio.create_task(run_pipeline(...))` (no `/execute` e no `/answer`):

```python
    task = asyncio.create_task(run_pipeline(project_id, card_id, execution_id=execution_id))
    task.add_done_callback(_log_task_result)
```

(no `/answer`, mantendo os kwargs `resume_stage=resume_stage, human_answer=message`).

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py -v`
Expected: PASS (todos, incluindo o novo).

- [ ] **Step 1.6: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/src/routes/runner.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipeline): try/except de topo em run_pipeline — excecao interna pausa o card (A1)"
```

---

### Task 2 (A1b): recovery no boot — Executions RUNNING órfãs viram PAUSED

**Files:**
- Create: `backend/src/services/startup_recovery.py`
- Modify: `backend/src/main.py` (lifespan)
- Test: `backend/tests/test_startup_recovery.py`

- [ ] **Step 2.1: Write the failing test**

Criar `backend/tests/test_startup_recovery.py`:

```python
import pytest
import src.models  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.models.activity_log import ActivityLog, ActivityType
from src.models.execution import Execution, ExecutionStatus
from src.models.project_registry import Project
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate
from src.services.startup_recovery import recover_orphan_executions


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


async def _card_running_em(maker, coluna: str) -> str:
    """Card na coluna dada + Execution RUNNING orfa (simula crash do backend)."""
    async with maker() as s:
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev", base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X"), project_id="p1")
        card.column_id = coluna
        s.add(Execution(card_id=card.id, status=ExecutionStatus.RUNNING,
                        command="pipeline", is_active=True, workflow_stage=coluna))
        await s.commit()
        return card.id


async def test_running_orfa_vira_paused_e_card_pausa(maker):
    card_id = await _card_running_em(maker, "implement")
    count = await recover_orphan_executions(session_maker=maker)
    assert count == 1
    async with maker() as s:
        ex = (await s.execute(select(Execution).where(Execution.card_id == card_id))).scalars().first()
        assert ex.status == ExecutionStatus.PAUSED
        assert ex.is_active is False
        assert "reiniciado" in (ex.workflow_error or "")
        card = await CardRepository(s).get_by_id(card_id)
        assert card.column_id == "paused"
        # comentario no card orienta a retomada via aba Interacao
        acts = (await s.execute(select(ActivityLog).where(
            ActivityLog.card_id == card_id,
            ActivityLog.activity_type == ActivityType.COMMENTED,
        ))).scalars().all()
        assert any("reiniciou" in (a.description or "") for a in acts)


async def test_sem_orfas_nao_faz_nada(maker):
    count = await recover_orphan_executions(session_maker=maker)
    assert count == 0
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_startup_recovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.startup_recovery'`.

- [ ] **Step 2.3: Implementar o sweep**

Criar `backend/src/services/startup_recovery.py`:

```python
"""Recovery no boot (A1b): Executions deixadas RUNNING por um restart viram PAUSED.

Sem isso, um crash/restart do backend deixa o run orfao (RUNNING para sempre) e o
card travado — e POST /answer exige PAUSED, entao nem a retomada manual funciona.
O sweep marca a Execution como PAUSED, move o card para `paused` (se a transicao
permitir) e comenta no card para o humano retomar pela aba Interacao.
"""

from datetime import datetime

from sqlalchemy import select

from ..database import async_session_maker
from ..models.execution import Execution, ExecutionStatus
from ..repositories.activity_repository import ActivityRepository
from ..repositories.card_repository import CardRepository

_RESUME_HINT = (
    "O servidor reiniciou durante a execução. "
    "Responda este comentário para retomar de onde parou."
)


async def recover_orphan_executions(session_maker=async_session_maker) -> int:
    """Marca como PAUSED toda Execution RUNNING (orfa de restart). Devolve o total."""
    async with session_maker() as s:
        rows = (await s.execute(
            select(Execution).where(Execution.status == ExecutionStatus.RUNNING)
        )).scalars().all()
        if not rows:
            return 0
        repo = CardRepository(s)
        for ex in rows:
            ex.status = ExecutionStatus.PAUSED
            ex.workflow_error = "backend reiniciado durante o run | recuperado no boot"
            ex.is_active = False
            ex.completed_at = datetime.utcnow()
            card = await repo.get_by_id(ex.card_id)
            if card and card.column_id != "paused":
                await repo.move(ex.card_id, "paused")  # falha de transicao: card fica onde esta
            try:
                await ActivityRepository(s).add_comment(ex.card_id, "agent", _RESUME_HINT)
            except Exception:  # noqa: BLE001 — comentario e best-effort
                pass
        await s.commit()
        return len(rows)
```

- [ ] **Step 2.4: Ligar no lifespan**

Em `backend/src/main.py`, dentro de `lifespan`, logo APÓS o bloco do `seed_dev_workflow` (depois do `print("[Server] Dev workflow seeded")`):

```python
    from .services.startup_recovery import recover_orphan_executions
    recovered = await recover_orphan_executions()
    if recovered:
        print(f"[Server] {recovered} execucao(oes) orfa(s) de restart pausada(s)")
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_startup_recovery.py -v`
Expected: PASS (2 testes).

- [ ] **Step 2.6: Commit**

```bash
git add backend/src/services/startup_recovery.py backend/src/main.py backend/tests/test_startup_recovery.py
git commit -m "feat(pipeline): recovery no boot — Executions RUNNING orfas de restart viram PAUSED (A1)"
```

---

### Task 3 (A2a): review falha-fechada — sem JSON parseável não aprova o diff

**Files:**
- Modify: `backend/src/services/findings.py`
- Modify: `backend/src/services/pipeline_service.py` (branch `review`)
- Test: `backend/tests/test_findings.py`, `backend/tests/test_pipeline_service.py`

- [ ] **Step 3.1: Write the failing tests**

Em `backend/tests/test_findings.py`, adicionar:

```python
def test_parse_review_findings_strict_devolve_none_sem_json():
    from src.services.findings import parse_review_findings_strict
    assert parse_review_findings_strict("") is None
    assert parse_review_findings_strict("parece tudo certo, aprovado!") is None
    assert parse_review_findings_strict('{"outra": "coisa"}') is None


def test_parse_review_findings_strict_parseia_json_valido():
    from src.services.findings import parse_review_findings_strict
    f = parse_review_findings_strict('bla ```json\n{"blocks":[],"fixNow":[{"titulo":"x"}]}\n```')
    assert f == {"blocks": [], "fixNow": [{"titulo": "x"}], "suggestions": []}
```

Em `backend/tests/test_pipeline_service.py`, adicionar:

```python
async def test_review_sem_json_nao_aprova_o_diff(maker):
    """Review que nunca devolve JSON: re-pede 1x e depois PAUSA (falha-fechada, A2)."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": ["parece tudo certo! aprovado."]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"      # NAO ready_to_merge
    assert counts.get("review") == 2                            # pediu de novo antes de pausar
    ex = await _last_execution(maker, card_id)
    assert "veredito" in (ex.workflow_error or "")


async def test_review_json_na_segunda_tentativa_aprova(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": [
        "sem json aqui",
        '{"blocks":[],"fixNow":[],"suggestions":[]}',
    ]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    assert counts.get("review") == 2
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_findings.py tests/test_pipeline_service.py -v -k "strict or sem_json or segunda_tentativa"`
Expected: FAIL — `ImportError` (strict não existe) e `test_review_sem_json_nao_aprova_o_diff` termina em `ready_to_merge`.

- [ ] **Step 3.3: Implementar `parse_review_findings_strict`**

Em `backend/src/services/findings.py`, adicionar após `parse_review_findings`:

```python
def parse_review_findings_strict(text: str) -> Optional[dict]:
    """Como parse_review_findings, mas devolve None quando o texto NAO contem nenhum
    JSON com os baldes. Falha-fechada: review nao-parseavel NAO pode aprovar o diff
    (o parser tolerante devolvia baldes vazios e liberava o caminho do merge)."""
    if not text:
        return None
    obj = _last_matching(
        text,
        lambda o: any(k in o for k in ("blocks", "fixNow", "suggestions")),
    )
    if obj is None:
        return None
    return {
        "blocks": _as_list(obj.get("blocks")),
        "fixNow": _as_list(obj.get("fixNow")),
        "suggestions": _as_list(obj.get("suggestions")),
    }
```

- [ ] **Step 3.4: Usar o strict no pipeline com 1 re-pedido**

Em `backend/src/services/pipeline_service.py`:

1. Trocar o import de `parse_review_findings` por `parse_review_findings_strict` (mantendo os demais).
2. No branch `elif col == "review":`, substituir a linha `f = parse_review_findings(res.text)` por:

```python
                f = parse_review_findings_strict(res.text)
                if f is None:
                    # falha-fechada: reviewer sem JSON re-explica o contrato e tenta 1x (A2)
                    await log.event("review sem JSON parseavel — re-pedindo o veredito")
                    retry_prompt = prompt + (
                        "\n\nSua resposta anterior nao continha o JSON de achados. Responda AGORA "
                        'somente com o JSON {"blocks": [...], "fixNow": [...], "suggestions": [...]} '
                        "(arrays vazios se o diff estiver aprovado)."
                    )
                    res = await stage_fn("review", worktree, retry_prompt, card_id=card_id, on_log=log,
                                         model=stage_model_for_column("review", card))
                    await log.flush()
                    await account(res)
                    if res.interrupted:
                        await finish_pause("interrompido pelo usuario",
                                           "O usuario parou a execucao para corrigir o rumo.")
                        return
                    if not res.ok:
                        await finish_pause("erro no re-pedido do review", res.error)
                        return
                    f = parse_review_findings_strict(res.text)
                    if f is None:
                        await finish_pause(
                            "review sem veredito parseavel", (res.text or "")[:1500],
                            question=("O revisor nao devolveu o JSON de achados apos 2 tentativas. "
                                      "Como devo proceder?"),
                        )
                        return
```

(o restante do branch — `blocking = ...` em diante — permanece igual).

- [ ] **Step 3.5: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_findings.py tests/test_pipeline_service.py -v`
Expected: PASS (todos).

- [ ] **Step 3.6: Commit**

```bash
git add backend/src/services/findings.py backend/src/services/pipeline_service.py backend/tests/test_findings.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipeline): review falha-fechada — sem JSON parseavel re-pede 1x e pausa, nunca aprova (A2)"
```

---

### Task 4 (A2b): estágio que termina sem output = pausa

**Files:**
- Modify: `backend/src/services/pipeline_service.py`
- Test: `backend/tests/test_pipeline_service.py`

- [ ] **Step 4.1: Write the failing test**

```python
async def test_estagio_sem_output_pausa(maker):
    """Turno vazio (ok=True, text='') nao pode contar como estagio concluido (A2)."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"plan": [""]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("implement") is None
    ex = await _last_execution(maker, card_id)
    assert "sem output" in (ex.workflow_error or "")
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py::test_estagio_sem_output_pausa -v`
Expected: FAIL — hoje plan vazio segue para implement.

- [ ] **Step 4.3: Implementar o check**

Em `backend/src/services/pipeline_service.py`, no laço principal, logo após o bloco `if not res.ok:` (e antes do `if col == "plan":`):

```python
            if not (res.text or "").strip():
                await finish_pause(
                    f"estagio {col} terminou sem output",
                    "O agente encerrou o turno sem produzir texto — provavel recusa ou turno abortado.",
                )
                return
```

E no fix-loop, logo após o `if not fix_res.ok:` existente:

```python
                    if not (fix_res.text or "").strip():
                        await finish_pause("fix-loop terminou sem output",
                                           "O agente encerrou o turno sem produzir texto.")
                        return
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py -v`
Expected: PASS. Atenção: `test_interrupt_pauses_card` usa `text=""` com `interrupted=True` — continua passando porque o check de `interrupted` vem ANTES do check de texto vazio.

- [ ] **Step 4.5: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipeline): estagio com turno vazio pausa em vez de avancar (A2)"
```

---

### Task 5 (A2c): snippet anti-parada-prematura + helper `build_stage_options`

O helper vira o ponto único de montagem de options do estágio (base para os perfis por modelo da onda N1).

**Files:**
- Modify: `backend/src/services/stage_runner.py`
- Test: `backend/tests/test_stage_runner_load.py`

- [ ] **Step 5.1: Write the failing test**

Em `backend/tests/test_stage_runner_load.py`, adicionar:

```python
def test_build_stage_options_inclui_snippet_de_autonomia():
    from src.services.stage_runner import build_stage_options
    opts = build_stage_options("implement", "/tmp/wt", "opus-4.8")
    append = opts.system_prompt["append"]
    assert "Operacao autonoma" in append
    assert "needs_human" in append          # o snippet preserva a valvula de escape
    assert opts.model == "claude-opus-4-8[1m]"
    assert opts.permission_mode == "acceptEdits"


def test_build_stage_options_sem_model_usa_default_do_cli():
    from src.services.stage_runner import build_stage_options
    opts = build_stage_options("plan", "/tmp/wt", None)
    assert getattr(opts, "model", None) is None
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stage_runner_load.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_stage_options'`.

- [ ] **Step 5.3: Implementar snippet + helper**

Em `backend/src/services/stage_runner.py`, adicionar após `STAGE_AGENTS`:

```python
# Padrao oficial Anthropic (anti-parada-prematura): sem isto, um agente que encerra o
# turno com um plano/promessa passa como estagio concluido e o pipeline commita o nada.
AUTONOMY_SNIPPET = (
    "\n\n## Operacao autonoma\n"
    "Voce opera de forma autonoma dentro de um pipeline; o usuario nao acompanha em tempo real. "
    "Antes de encerrar o turno, verifique seu ultimo paragrafo: se for um plano, uma analise, uma "
    "pergunta retorica ou uma promessa de trabalho nao feito, execute esse trabalho AGORA com tool "
    "calls em vez de encerrar. Encerre somente com o resultado final no formato pedido — ou com "
    "`needs_human`/`pendingQuestions` quando a decisao for genuinamente humana."
)


def build_stage_options(stage_key: str, worktree: str, model: "str | None") -> ClaudeAgentOptions:
    """Ponto unico de montagem das options do estagio (futuro plug de perfis por modelo)."""
    body, tools = load_stage_agent(stage_key)
    options_kwargs = dict(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": body + AUTONOMY_SNIPPET},
        allowed_tools=tools,
        permission_mode="acceptEdits",
    )
    if model:
        options_kwargs["model"] = resolve_model_id(model)
    return ClaudeAgentOptions(**options_kwargs)
```

E em `run_stage`, substituir o bloco atual de montagem (do `body, tools = load_stage_agent(stage_key)` até `options = ClaudeAgentOptions(**options_kwargs)`) por:

```python
    options = build_stage_options(stage_key, worktree, model)
```

(a variável `tools` não é mais usada em `run_stage`; `body` idem).

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stage_runner_load.py tests/test_pipeline_model_wiring.py -v`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add backend/src/services/stage_runner.py backend/tests/test_stage_runner_load.py
git commit -m "feat(stage): snippet anti-parada-prematura no system prompt + build_stage_options unico (A2)"
```

---

### Task 6 (A3a): coluna `paused` no início do board + seed vira upsert

O seed é config-as-code (não há CRUD de workflow); passa a ATUALIZAR a row `dev` existente para o board refletir mudanças de config sem apagar o DB.

**Files:**
- Modify: `backend/src/services/workflow_seed.py`
- Test: `backend/tests/test_workflow_seed.py`

- [ ] **Step 6.1: Write the failing test**

Em `backend/tests/test_workflow_seed.py`, adicionar (seguindo o padrão de fixture/sessão do próprio arquivo — leia-o antes; se ele asserta a ordem antiga das colunas, atualize essas asserções para a nova ordem `paused, backlog, plan, implement, review, validate_ci, ready_to_merge, done`):

```python
async def test_paused_e_a_primeira_coluna(session):
    from src.services.workflow_seed import seed_dev_workflow, DEV_WORKFLOW_ID
    from src.models.workflow import Workflow
    from sqlalchemy import select
    await seed_dev_workflow(session)
    wf = (await session.execute(select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID))).scalar_one()
    ordered = sorted(wf.columns, key=lambda c: c["order"])
    assert ordered[0]["key"] == "paused"
    assert [c["key"] for c in ordered] == [
        "paused", "backlog", "plan", "implement", "review",
        "validate_ci", "ready_to_merge", "done",
    ]


async def test_seed_atualiza_workflow_existente(session):
    """Seed e upsert (config-as-code): row existente converge para o codigo."""
    from src.services.workflow_seed import seed_dev_workflow, DEV_WORKFLOW_ID, DEV_COLUMNS
    from src.models.workflow import Workflow
    from sqlalchemy import select
    await seed_dev_workflow(session)
    wf = (await session.execute(select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID))).scalar_one()
    wf.columns = [{"key": "so_uma", "label": "X", "order": 0}]
    await session.commit()
    await seed_dev_workflow(session)
    wf2 = (await session.execute(select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID))).scalar_one()
    assert len(wf2.columns) == len(DEV_COLUMNS)
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_seed.py -v`
Expected: FAIL nos dois novos (paused está com order 7; seed retorna cedo se a row existe).

- [ ] **Step 6.3: Implementar**

Em `backend/src/services/workflow_seed.py`:

1. Reordenar `DEV_COLUMNS` — `paused` passa a `order: 0` e vem PRIMEIRO na lista; os demais deslocam +1 (backlog 1, plan 2, implement 3, review 4, validate_ci 5, ready_to_merge 6, done 7). Manter todos os demais campos de cada coluna como estão.
2. Substituir `seed_dev_workflow` por upsert:

```python
async def seed_dev_workflow(session: AsyncSession) -> None:
    """Cria OU atualiza o workflow dev (config-as-code: o seed e a fonte de verdade;
    nao ha CRUD de workflow, entao mudancas de config chegam ao DB por aqui)."""
    existing = (await session.execute(
        select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID)
    )).scalar_one_or_none()
    if existing is None:
        session.add(Workflow(
            id=DEV_WORKFLOW_ID,
            name="Desenvolvimento (DevKit)",
            columns=DEV_COLUMNS,
            transitions=DEV_TRANSITIONS,
        ))
    else:
        existing.columns = DEV_COLUMNS
        existing.transitions = DEV_TRANSITIONS
    await session.commit()
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_seed.py tests/test_workflows_routes.py tests/test_move_by_config.py -v`
Expected: PASS (transições não mudaram; só ordem de colunas e upsert).

- [ ] **Step 6.5: Commit**

```bash
git add backend/src/services/workflow_seed.py backend/tests/test_workflow_seed.py
git commit -m "feat(board): coluna paused vira a primeira do board; seed do workflow dev vira upsert (A3)"
```

---

### Task 7 (A3b): toast global de pausa + contador "aguardando você" no TopNav

**Files:**
- Create: `frontend/src/components/Toast/ToastContainer.tsx`
- Create: `frontend/src/components/Toast/Toast.module.css`
- Modify: `frontend/src/App.tsx` (handler `onCardMoved` + render + pausedCount)
- Modify: `frontend/src/layouts/WorkspaceLayout.tsx` (prop `pausedCount`)
- Modify: `frontend/src/components/Navigation/TopNav.tsx` (sino → badge funcional)

- [ ] **Step 7.1: Criar o ToastContainer**

`frontend/src/components/Toast/ToastContainer.tsx`:

```tsx
import { createPortal } from 'react-dom';
import type { Toast } from '../../hooks/useToast';
import styles from './Toast.module.css';

interface Props {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

/** Toasts globais (canto inferior direito). Hoje usado para avisar pausa de card (A3). */
export function ToastContainer({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;
  return createPortal(
    <div className={styles.container} role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className={`${styles.toast} ${styles[t.type]}`} onClick={() => onDismiss(t.id)}>
          <div className={styles.title}>{t.title}</div>
          {t.message && <div className={styles.message}>{t.message}</div>}
        </div>
      ))}
    </div>,
    document.body
  );
}
```

`frontend/src/components/Toast/Toast.module.css`:

```css
.container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
}

.toast {
  background: var(--surface-2, #1e1e2e);
  color: var(--text-primary, #e4e4e7);
  border: 1px solid var(--border, #3f3f46);
  border-left: 4px solid #f59e0b;
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  cursor: pointer;
  animation: slideIn 0.2s ease-out;
}

.toast.error { border-left-color: #ef4444; }
.toast.success { border-left-color: #22c55e; }
.toast.info { border-left-color: #f59e0b; }

.title { font-weight: 600; font-size: 13px; }
.message { font-size: 12px; opacity: 0.85; margin-top: 4px; }

@keyframes slideIn {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
```

- [ ] **Step 7.2: Ligar no App**

Em `frontend/src/App.tsx`:

1. Imports novos:

```tsx
import { useToast } from './hooks/useToast';
import { ToastContainer } from './components/Toast/ToastContainer';
```

2. Dentro de `App()`, junto aos outros hooks (antes do `useCardWebSocket`):

```tsx
  const { toasts, addToast, removeToast } = useToast();
  const pausedCount = cards.filter(c => c.columnId === 'paused').length;
```

3. No callback `onCardMoved` existente, adicionar ANTES do `setCards(...)` (a mensagem do WS já traz `fromColumn`/`toColumn`):

```tsx
      if (message.toColumn === 'paused' && message.fromColumn !== 'paused') {
        addToast({
          type: 'info',
          title: '⏸ Aguardando você',
          message: `"${message.card.title}" pausou e precisa da sua resposta.`,
        });
      }
```

E acrescentar `addToast` ao array de dependências do `useCallback` (`[getWorkflowStatus, addToast]`).

4. No JSX retornado pelo App, localizar o `return (` principal e renderizar o container como irmão do `WorkspaceLayout` (envolvendo em fragment `<>...</>` se necessário):

```tsx
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
```

5. Passar `pausedCount={pausedCount}` para o `<WorkspaceLayout ...>`.

- [ ] **Step 7.3: Propagar pelo WorkspaceLayout e TopNav**

`frontend/src/layouts/WorkspaceLayout.tsx` — adicionar à interface e repassar:

```tsx
interface WorkspaceLayoutProps {
  children: ReactNode;
  currentModule: ModuleType;
  onNavigate: (module: ModuleType) => void;
  currentProjectId: string | null;
  onProjectSwitch: (projectId: string) => void;
  pausedCount?: number;
}

const WorkspaceLayout = ({ children, currentModule, onNavigate, currentProjectId, onProjectSwitch, pausedCount = 0 }: WorkspaceLayoutProps) => {
```

e no `<TopNav ...>`: `pausedCount={pausedCount}`.

`frontend/src/components/Navigation/TopNav.tsx` — adicionar `pausedCount?: number` à `TopNavProps` (e ao destructuring, com default `= 0`); substituir o botão decorativo "Notifications" por:

```tsx
        <button
          className={styles.iconBtn}
          title={pausedCount > 0 ? `${pausedCount} card(s) aguardando sua resposta` : 'Nenhum card aguardando você'}
          onClick={() => onNavigate('kanban')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          {pausedCount > 0 && <span className={styles.notifBadge}>{pausedCount}</span>}
        </button>
```

(remover o `<span className={styles.notifDot}></span>` estático). Em `TopNav.module.css`, adicionar:

```css
.notifBadge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 8px;
  background: #f59e0b;
  color: #1c1917;
  font-size: 10px;
  font-weight: 700;
  line-height: 15px;
  text-align: center;
}
```

(confira que `.iconBtn` tem `position: relative`; se não tiver, adicione).

- [ ] **Step 7.4: Verificar tipos**

Run: `cd frontend && npx tsc --noEmit`
Expected: apenas os ~7 erros pré-existentes `Cannot find namespace 'NodeJS'` (confirme com `git stash && npx tsc --noEmit` se ficar em dúvida).

- [ ] **Step 7.5: Commit**

```bash
git add frontend/src/components/Toast frontend/src/App.tsx frontend/src/layouts/WorkspaceLayout.tsx frontend/src/components/Navigation/TopNav.tsx frontend/src/components/Navigation/TopNav.module.css
git commit -m "feat(board): toast global de pausa + contador 'aguardando voce' no TopNav (A3)"
```

---

### Task 8 (A5a): persistir tokens, modelos usados e iterações do fix-loop

**Files:**
- Modify: `backend/src/services/stage_runner.py` (`StageResult.usage`)
- Modify: `backend/src/models/execution.py` (coluna `fix_iterations`)
- Modify: `backend/src/services/light_migrations.py`
- Modify: `backend/src/services/pipeline_service.py` (acumular + persistir)
- Modify: `backend/src/routes/runner.py` (expor na API)
- Test: `backend/tests/test_pipeline_service.py`

- [ ] **Step 8.1: Write the failing test**

Em `backend/tests/test_pipeline_service.py`, adicionar:

```python
async def test_tokens_modelos_e_iteracoes_persistidos(maker):
    """A5: usage do ResultMessage + modelos por etapa + fix_iterations ficam na Execution."""
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        text = ('{"blocks":[{"titulo":"x"}],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok")
        # segunda revisao aprova
        if stage_key == "review" and fake.review_calls > 0:
            text = '{"blocks":[],"fixNow":[]}'
        if stage_key == "review":
            fake.review_calls += 1
        return StageResult(ok=True, text=text, cost_usd=0.01,
                           usage={"input_tokens": 100, "output_tokens": 50})
    fake.review_calls = 0

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    ex = await _last_execution(maker, card_id)
    # 5 estagios (plan, implement, review, fix-implement, re-review) x (100 in + 50 out)
    assert ex.input_tokens == 500
    assert ex.output_tokens == 250
    assert ex.total_tokens == 750
    assert ex.fix_iterations == 1
    assert "opus-4.8" in (ex.model_used or "")
```

- [ ] **Step 8.2: Run test to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py::test_tokens_modelos_e_iteracoes_persistidos -v`
Expected: FAIL — `StageResult` não aceita `usage`.

- [ ] **Step 8.3: `StageResult.usage` + captura no run_stage**

Em `backend/src/services/stage_runner.py`:

1. No dataclass `StageResult`, adicionar o campo:

```python
    usage: Optional[dict] = None
```

2. Em `run_stage`, inicializar `usage = None` junto de `cost = None`; no branch do `ResultMessage`:

```python
            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                usage = getattr(message, "usage", None) or None
```

3. Incluir `usage=usage` nos DOIS retornos de `StageResult` (o do `except` e o final).

- [ ] **Step 8.4: Coluna `fix_iterations` + migração**

Em `backend/src/models/execution.py`, após `execution_cost`:

```python
    # Telemetria de autonomia (A5): iteracoes do fix-loop deste run
    fix_iterations = Column(Integer, nullable=True)
```

Em `backend/src/services/light_migrations.py`, adicionar à lista `_COLUMNS`:

```python
    ("executions", "fix_iterations", "INTEGER"),
```

- [ ] **Step 8.5: Acumular e persistir no pipeline**

Em `backend/src/services/pipeline_service.py`, dentro de `run_pipeline`:

1. MOVER as inicializações `iteration = 0` e `plan_text: Optional[str] = None` (hoje após a seção de worktree) para ANTES da definição de `finish_pause`, junto de `total_cost = 0.0`, e adicionar:

```python
        tokens = {"input": 0, "output": 0}
        models_used: set[str] = set()
```

2. Trocar `account` por versão que acumula usage e modelo:

```python
        async def account(res, model_alias: "str | None" = None):
            nonlocal total_cost
            if res is None:
                return
            if res.cost_usd:
                total_cost += float(res.cost_usd)
            u = getattr(res, "usage", None)
            if isinstance(u, dict):
                tokens["input"] += int(u.get("input_tokens") or 0) \
                    + int(u.get("cache_creation_input_tokens") or 0) \
                    + int(u.get("cache_read_input_tokens") or 0)
                tokens["output"] += int(u.get("output_tokens") or 0)
            if model_alias:
                models_used.add(model_alias)
```

3. Criar o helper de persistência (logo após `account`):

```python
        def persist_run_stats() -> None:
            execution.input_tokens = tokens["input"] or None
            execution.output_tokens = tokens["output"] or None
            execution.total_tokens = (tokens["input"] + tokens["output"]) or None
            execution.model_used = ",".join(sorted(models_used)) or None
            execution.fix_iterations = iteration
            execution.execution_cost = total_cost or None
```

4. Em `finish_pause`, substituir a linha `execution.execution_cost = total_cost or None` por `persist_run_stats()`. No epílogo de sucesso, idem.
5. Atualizar as chamadas de `account`:
   - estágio principal: `await account(res, stage_model_for_column(col, card))`
   - re-pedido do review (Task 3): `await account(res, stage_model_for_column("review", card))`
   - fix-loop: `await account(fix_res, stage_model_for_column("implement", card))`

- [ ] **Step 8.6: Expor na API**

Em `backend/src/routes/runner.py`, no dict `"execution"` de `get_card_execution`, adicionar:

```python
            "fixIterations": execution.fix_iterations,
            "modelUsed": execution.model_used,
            "totalTokens": execution.total_tokens,
```

- [ ] **Step 8.7: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_pipeline_service.py tests/test_stage_runner_load.py -v`
Expected: PASS (todos; os fakes antigos sem `usage` continuam válidos — campo default None).

- [ ] **Step 8.8: Commit**

```bash
git add backend/src/services/stage_runner.py backend/src/models/execution.py backend/src/services/light_migrations.py backend/src/services/pipeline_service.py backend/src/routes/runner.py backend/tests/test_pipeline_service.py
git commit -m "feat(telemetria): tokens/modelos/fix_iterations persistidos na Execution e expostos na API (A5)"
```

---

### Task 9 (A5b): custo e tokens do run visíveis no painel

**Files:**
- Modify: `frontend/src/api/pipeline.ts` (tipos)
- Modify: `frontend/src/components/PipelineControls/PipelineControls.tsx` (estado + prop)
- Modify: `frontend/src/components/LogsModal/LogsModal.tsx` (metadata "Custo do run")

- [ ] **Step 9.1: Tipos da API**

Em `frontend/src/api/pipeline.ts`, na interface `PipelineExecution`, adicionar:

```typescript
  fixIterations?: number | null;
  modelUsed?: string | null;
  totalTokens?: number | null;
```

- [ ] **Step 9.2: PipelineControls guarda e repassa o custo**

Em `frontend/src/components/PipelineControls/PipelineControls.tsx`:

1. Novo estado após `prUrl`:

```tsx
  const [runMeta, setRunMeta] = useState<{ costUsd?: number | null; totalTokens?: number | null } | null>(null);
```

2. Em `handleOpenLogs`, dentro do `if (state.execution)`, adicionar:

```tsx
          setRunMeta({ costUsd: state.execution.costUsd, totalTokens: state.execution.totalTokens });
```

3. No effect do `ready_to_merge` (o que busca `prUrl`), dentro do `if (alive && state.execution?.prUrl)`, adicionar a mesma linha `setRunMeta({ costUsd: state.execution.costUsd, totalTokens: state.execution.totalTokens });` logo após o `setPrUrl(...)`.
4. No `<LogsModal ...>`, passar `runCostUsd={runMeta?.costUsd ?? undefined}` e `runTotalTokens={runMeta?.totalTokens ?? undefined}`.

- [ ] **Step 9.3: LogsModal exibe o custo real do run**

Em `frontend/src/components/LogsModal/LogsModal.tsx`:

1. Props novas na interface `LogsModalProps` (e no destructuring):

```tsx
  runCostUsd?: number;       // custo real do run (Execution.execution_cost)
  runTotalTokens?: number;   // tokens do run (Execution.total_tokens)
```

2. No painel de metadata, após o item "Status" (antes do bloco `costStats`), adicionar:

```tsx
            {(runCostUsd !== undefined && runCostUsd !== null) && (
              <div className={`${styles.metadataItem} ${styles.highlight}`}>
                <div className={styles.metadataIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="1" x2="12" y2="23"/>
                    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                  </svg>
                </div>
                <div className={styles.metadataContent}>
                  <div className={styles.metadataLabel}>Custo do run</div>
                  <div className={styles.metadataValue}>
                    {formatCost(runCostUsd)}
                    {runTotalTokens ? ` · ${runTotalTokens.toLocaleString('pt-BR')} tokens` : ''}
                  </div>
                </div>
              </div>
            )}
```

- [ ] **Step 9.4: Verificar tipos**

Run: `cd frontend && npx tsc --noEmit`
Expected: apenas os erros pré-existentes.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/api/pipeline.ts frontend/src/components/PipelineControls/PipelineControls.tsx frontend/src/components/LogsModal/LogsModal.tsx
git commit -m "feat(painel): custo e tokens reais do run visiveis no LogsModal (A5)"
```

---

### Task 10 (A6): chat — contexto do workflow real, atividades por projeto, projectId no template

**Files:**
- Modify: `backend/src/repositories/activity_repository.py` (`get_recent_activities` com `project_id`)
- Modify: `backend/src/services/chat_service.py` (`_get_kanban_context` + `get_system_prompt`)
- Modify: `backend/src/agent_chat.py` (`DEFAULT_SYSTEM_PROMPT`)
- Test: `backend/tests/test_chat_service_scoped.py`

- [ ] **Step 10.1: Write the failing tests**

Em `backend/tests/test_chat_service_scoped.py`, adicionar (siga o padrão de fixture do próprio arquivo — leia-o antes; os testes abaixo assumem um `maker` de engine in-memory; monte os dados com `async_session_maker` monkeypatchado como os testes vizinhos fazem):

```python
async def test_contexto_inclui_colunas_do_workflow_real(maker, monkeypatch):
    """Cards em paused/validate_ci/ready_to_merge aparecem no contexto do chat (A6)."""
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project
    from src.repositories.card_repository import CardRepository
    from src.schemas.card import CardCreate

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev"))
        repo = CardRepository(s)
        c1 = await repo.create(CardCreate(title="Tarefa pausada"), project_id="p1")
        c1.column_id = "paused"
        c2 = await repo.create(CardCreate(title="Aguardando merge"), project_id="p1")
        c2.column_id = "ready_to_merge"
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    ctx = await cs.ChatService()._get_kanban_context("p1")
    assert "Tarefa pausada" in ctx
    assert "Aguardando merge" in ctx


async def test_atividades_escopadas_por_projeto(maker, monkeypatch):
    """Atividade de outro projeto NAO vaza para o contexto do chat (A6)."""
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project
    from src.repositories.card_repository import CardRepository
    from src.repositories.activity_repository import ActivityRepository
    from src.schemas.card import CardCreate

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj1", path="/tmp/p1", workflow_id="dev"))
        s.add(Project(id="p2", name="proj2", path="/tmp/p2", workflow_id="dev"))
        repo = CardRepository(s)
        await repo.create(CardCreate(title="Do projeto 1"), project_id="p1")
        c2 = await repo.create(CardCreate(title="SEGREDO do projeto 2"), project_id="p2")
        await ActivityRepository(s).add_comment(c2.id, "human", "comentario p2")
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    ctx = await cs.ChatService()._get_kanban_context("p1")
    assert "SEGREDO do projeto 2" not in ctx


async def test_system_prompt_contem_projectid_e_worktrees(maker, monkeypatch):
    from src.services import chat_service as cs
    from src.services.workflow_seed import seed_dev_workflow
    from src.models.project_registry import Project

    async with maker() as s:
        await seed_dev_workflow(s)
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev"))
        await s.commit()

    monkeypatch.setattr(cs, "async_session_maker", maker)
    sp = await cs.ChatService().get_system_prompt("p1")
    assert '"projectId": "p1"' in sp
    assert ".worktrees/" in sp
    assert "/api/activities/card/" in sp
```

- [ ] **Step 10.2: Run tests to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_chat_service_scoped.py -v`
Expected: FAIL nos 3 novos (colunas paused/ready_to_merge não renderizam; atividades vazam; system prompt sem projectId).

- [ ] **Step 10.3: `get_recent_activities` com escopo de projeto**

Em `backend/src/repositories/activity_repository.py`, mudar a assinatura e a query:

```python
    async def get_recent_activities(
        self, limit: int = 10, offset: int = 0, project_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
```

e após o `.where(Card.archived == False)` existente, adicionar:

```python
        if project_id:
            query = query.where(Card.project_id == project_id)
```

(construir a query em duas etapas: `query = select(...).join(...).where(Card.archived == False)`, depois o `if`, depois `query = query.order_by(...).limit(limit).offset(offset)`).

- [ ] **Step 10.4: `_get_kanban_context` dirigido pelo workflow config**

Em `backend/src/services/chat_service.py`:

1. Imports novos no topo:

```python
from sqlalchemy import select
from ..models.workflow import Workflow
from ..services.workflow_seed import DEV_COLUMNS
```

2. Substituir o corpo de `_get_kanban_context` (mantendo assinatura e o try/except externo) por:

```python
        try:
            async with async_session_maker() as session:
                card_repo = CardRepository(session)
                activity_repo = ActivityRepository(session)
                project = await ProjectRepository(session).get_by_id(project_id)

                cards = await card_repo.get_all(project_id=project_id)
                activities = await activity_repo.get_recent_activities(limit=5, project_id=project_id)

                # Colunas vem do workflow config do projeto (fallback: seed dev)
                workflow_id = (project.workflow_id if project else None) or "dev"
                wf = (await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )).scalar_one_or_none()
                wf_columns = sorted(wf.columns, key=lambda c: c.get("order", 0)) if wf else DEV_COLUMNS

                emojis = {
                    "paused": "⏸", "backlog": "📋", "plan": "📝", "implement": "🔨",
                    "review": "👀", "validate_ci": "🧪", "ready_to_merge": "🔀", "done": "✅",
                }
                by_col: Dict[str, List] = {c["key"]: [] for c in wf_columns}
                for card in cards:
                    by_col.setdefault(card.column_id, []).append(card)

                lines = ["=== KANBAN STATUS ==="]
                for col in wf_columns:
                    col_cards = by_col.get(col["key"], [])
                    if not col_cards:
                        continue
                    emoji = emojis.get(col["key"], "▪")
                    lines.append(f"\n{emoji} {col['label']} ({len(col_cards)}):")
                    for card in col_cards[:5]:
                        time_str = self._format_relative_time(card.created_at)
                        lines.append(f"  - [{card.id[:8]}] \"{card.title}\" ({time_str})")
                        if card.description:
                            lines.append(f"    -> {self._truncate(card.description, 60)}")

                summary = " | ".join(
                    f"{len(by_col.get(c['key'], []))} {c['key']}" for c in wf_columns
                )
                lines.append(f"\n📊 Resumo: {summary}")

                if activities:
                    lines.append("\n🕐 Ultimas atividades (deste projeto):")
                    for act in activities[:5]:
                        time_str = self._format_relative_time(
                            datetime.fromisoformat(act["timestamp"])
                        )
                        card_title = self._truncate(act["cardTitle"], 30)
                        if act["type"] == "moved":
                            lines.append(f"  - \"{card_title}\" movido para {act['toColumn']} ({time_str})")
                        elif act["type"] == "created":
                            lines.append(f"  - \"{card_title}\" criado ({time_str})")
                        elif act["type"] == "commented":
                            lines.append(f"  - \"{card_title}\" comentado ({time_str})")
                        else:
                            lines.append(f"  - \"{card_title}\" {act['type']} ({time_str})")

                lines.append("===================")
                return "\n".join(lines)

        except Exception as e:
            print(f"[ChatService] Error getting kanban context: {e}")
            return ""
```

3. Substituir `get_system_prompt` por:

```python
    async def get_system_prompt(self, project_id: str) -> str:
        """System prompt: base + bloco do projeto atual + contexto Kanban (tudo escopado)."""
        kanban_context = await self._get_kanban_context(project_id)
        project_block = (
            "\n\n## Projeto atual\n"
            f"- projectId: {project_id}\n"
            f"- Ao criar cards via API, SEMPRE inclua \"projectId\": \"{project_id}\" no JSON "
            "(sem isso o card fica sem projeto e nao aparece no board).\n"
            "- As worktrees dos cards em execucao vivem em `.worktrees/card-<id8>/` na raiz do "
            "projeto (seu cwd) — voce pode ler o codigo delas com Read/Glob/Grep.\n"
            "- Historico de um card: `curl -s http://localhost:3001/api/activities/card/<cardId>` "
            "(comentarios/decisoes) e `curl -s http://localhost:3001/api/projects/"
            f"{project_id}/cards/<cardId>/execution` (ultimo run + logs).\n"
        )
        if kanban_context:
            return f"{DEFAULT_SYSTEM_PROMPT}{project_block}\n\n{kanban_context}"
        return f"{DEFAULT_SYSTEM_PROMPT}{project_block}"
```

- [ ] **Step 10.5: Template de criação de card com projectId**

Em `backend/src/agent_chat.py`, dentro da string `DEFAULT_SYSTEM_PROMPT` (é uma string Python triple-quoted; as cercas de código do curl fazem parte do texto e permanecem):

1. Trocar a linha `Use the Bash tool to call the API directly:` por
   `Use the Bash tool to call the API directly (replace PROJECT_ID with the projectId from the "Projeto atual" section below):`
2. No JSON do exemplo curl, adicionar a linha `"projectId": "PROJECT_ID",` logo após a linha da `"description"`.
3. Remover a linha `"modelTest": "haiku-4.5",` do exemplo curl.
4. Remover a linha `- Test: haiku-4.5 (fast for tests)` da seção "Model defaults" (a etapa test não existe no pipeline).

- [ ] **Step 10.6: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_chat_service_scoped.py tests/test_chat_routes_scoped.py tests/test_chat_repository.py -v`
Expected: PASS (novos e existentes).

- [ ] **Step 10.7: Commit**

```bash
git add backend/src/repositories/activity_repository.py backend/src/services/chat_service.py backend/src/agent_chat.py backend/tests/test_chat_service_scoped.py
git commit -m "feat(chat): contexto do workflow real (incl. paused/ready_to_merge), atividades por projeto e projectId no template (A6)"
```

---

### Task 11 (A4a): campos `Card.requested_by` e `Project.objective`

**Files:**
- Modify: `backend/src/models/card.py`, `backend/src/models/project_registry.py`
- Modify: `backend/src/services/light_migrations.py`
- Modify: `backend/src/schemas/card.py` (CardCreate/CardResponse)
- Modify: `backend/src/repositories/card_repository.py` (create)
- Modify: `backend/src/repositories/project_repository.py` (create)
- Modify: `backend/src/routes/projects_registry.py` (bodies + _to_dict)
- Modify: `backend/src/routes/cards.py` (card_to_dict)
- Test: `backend/tests/test_card_repository.py`, `backend/tests/test_projects_registry_routes.py`

- [ ] **Step 11.1: Write the failing tests**

Em `backend/tests/test_card_repository.py`, adicionar (siga a fixture de sessão do próprio arquivo):

```python
async def test_create_persiste_requested_by(session):
    from src.repositories.card_repository import CardRepository
    from src.schemas.card import CardCreate
    repo = CardRepository(session)
    card = await repo.create(CardCreate(title="T", requestedBy="PO Maria"), project_id=None)
    assert card.requested_by == "PO Maria"
```

Em `backend/tests/test_projects_registry_routes.py`, adicionar (siga o padrão httpx/ASGITransport do próprio arquivo):

```python
async def test_create_e_patch_objective(client):
    r = await client.post("/api/registry/projects", json={
        "name": "P", "path": "/tmp/obj-test", "objective": "ERP de gestao"
    })
    assert r.status_code == 201
    assert r.json()["project"]["objective"] == "ERP de gestao"
    pid = r.json()["project"]["id"]

    r2 = await client.patch(f"/api/registry/projects/{pid}", json={"objective": "novo objetivo"})
    assert r2.status_code == 200
    assert r2.json()["project"]["objective"] == "novo objetivo"
```

- [ ] **Step 11.2: Run tests to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_card_repository.py tests/test_projects_registry_routes.py -v -k "requested_by or objective"`
Expected: FAIL (campos não existem).

- [ ] **Step 11.3: Models + migração**

`backend/src/models/card.py` — após `project_id`:

```python
    # Quem pediu (A4): texto livre (nome/papel: dev, PO, CEO) — calibra as decisoes dos agentes
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
```

`backend/src/models/project_registry.py` — após `rules_file`:

```python
    # Objetivo de negocio do projeto (A4) — injetado no prompt dos agentes de estagio
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`backend/src/services/light_migrations.py` — adicionar a `_COLUMNS`:

```python
    ("cards", "requested_by", "VARCHAR(120)"),
    ("projects", "objective", "TEXT"),
```

- [ ] **Step 11.4: Schemas + repos + rotas**

1. `backend/src/schemas/card.py` — em `CardCreate`, adicionar:

```python
    requested_by: Optional[str] = Field(None, alias="requestedBy", max_length=120)
```

Em `CardResponse`, adicionar:

```python
    requested_by: Optional[str] = Field(None, alias="requestedBy")
```

2. `backend/src/repositories/card_repository.py` — no método `create`, no construtor `Card(...)` (o que já passa `column_id="backlog"` etc.), adicionar `requested_by=card_data.requested_by,` — se o construtor for por `model_dump`, garanta que o campo novo entre; leia o método antes de editar.
3. `backend/src/repositories/project_repository.py` — no método `create`, adicionar o parâmetro `objective: "str | None" = None` (espelhando o padrão de `rules_file`) e passá-lo ao construtor `Project(...)`.
4. `backend/src/routes/projects_registry.py`:
   - `ProjectCreateBody`: adicionar `objective: Optional[str] = None`
   - `ProjectPatchBody`: adicionar `objective: Optional[str] = None`
   - `_to_dict`: adicionar `"objective": p.objective,`
   - `create_project`: passar `objective=body.objective` na chamada `repo.create(...)`
5. `backend/src/routes/cards.py` — no `card_to_dict`, adicionar `"requestedBy": card.requested_by,` (localize o dict de serialização no topo do arquivo).

- [ ] **Step 11.5: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_card_repository.py tests/test_projects_registry_routes.py tests/test_cards_project_scope_repo.py -v`
Expected: PASS.

- [ ] **Step 11.6: Commit**

```bash
git add backend/src/models backend/src/schemas/card.py backend/src/repositories backend/src/routes/projects_registry.py backend/src/routes/cards.py backend/src/services/light_migrations.py backend/tests/test_card_repository.py backend/tests/test_projects_registry_routes.py
git commit -m "feat(dados): Card.requested_by + Project.objective com migracao leve e API (A4)"
```

---

### Task 12 (A4b): contexto do projeto/solicitante no prompt dos estágios + fix do rules_file

**Files:**
- Modify: `backend/src/services/stage_runner.py` (`build_stage_prompt`)
- Modify: `backend/src/services/pipeline_service.py` (passar `extra["context"]`)
- Modify: `devkit/.claude/agents/sismais-dev-planner.md`, `sismais-dev-implementer.md`, `sismais-dev-reviewer.md`
- Test: `backend/tests/test_stage_runner_load.py`, `backend/tests/test_pipeline_service.py`

- [ ] **Step 12.1: Write the failing tests**

Em `backend/tests/test_stage_runner_load.py`:

```python
def test_prompt_inclui_contexto_do_projeto():
    from src.services.stage_runner import build_stage_prompt
    ctx = {"project_name": "GMS Web", "objective": "ERP para gestao de oficinas",
           "rules_file": "REGRAS.md", "requested_by": "PO Maria"}
    p = build_stage_prompt("implement", "Titulo", "Desc", "/wt", {"context": ctx})
    assert "GMS Web" in p
    assert "ERP para gestao de oficinas" in p
    assert "REGRAS.md" in p
    assert "AGENTS.md" not in p          # hardcode removido: usa o rules_file do projeto
    assert "PO Maria" in p


def test_prompt_sem_contexto_usa_default_agents_md():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("implement", "Titulo", "Desc", "/wt", {})
    assert "AGENTS.md" in p
```

Em `backend/tests/test_pipeline_service.py`:

```python
async def test_prompt_do_estagio_recebe_contexto_do_projeto(maker):
    """A4: objetivo do projeto e solicitante chegam ao prompt de todos os estagios."""
    async with maker() as s:
        from sqlalchemy import select as _sel
        p = (await s.execute(_sel(Project).where(Project.id == "p1"))).scalar_one_or_none()
        if p is None:
            s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev",
                          base_branch="main", objective="ERP de gestao"))
        else:
            p.objective = "ERP de gestao"
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X", requestedBy="CEO"), project_id="p1")
        await s.commit()
        card_id = card.id

    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    for stage in ("plan", "implement", "review"):
        assert "ERP de gestao" in seen[stage][0], stage
        assert "CEO" in seen[stage][0], stage
```

Nota: este teste cria o projeto direto (sem `_make_project_card`) para setar `objective`.

- [ ] **Step 12.2: Run tests to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stage_runner_load.py tests/test_pipeline_service.py -v -k "contexto"`
Expected: FAIL.

- [ ] **Step 12.3: Header contextual em `build_stage_prompt`**

Em `backend/src/services/stage_runner.py`, dentro de `build_stage_prompt`, substituir a linha `header = f"Voce trabalha no repositorio em \`{worktree}\` (worktree isolada do card)."` por:

```python
    ctx = extra.get("context") or {}
    rules_file = ctx.get("rules_file") or "AGENTS.md"
    ctx_lines = [f"Voce trabalha no repositorio em `{worktree}` (worktree isolada do card)."]
    if ctx.get("project_name"):
        ctx_lines.append(f"Projeto: {ctx['project_name']}.")
    if ctx.get("objective"):
        ctx_lines.append(f"Objetivo do projeto: {ctx['objective']}")
    if ctx.get("requested_by"):
        ctx_lines.append(
            f"Solicitante do card: {ctx['requested_by']} — calibre profundidade e comunicacao para esse perfil."
        )
    ctx_lines.append(f"Regras do projeto: siga o `{rules_file}` se existir na worktree.")
    header = "\n".join(ctx_lines)
```

E no prompt do `implement` (branch sem findings), remover a frase hardcoded `"Siga o AGENTS.md do projeto se existir. "` (a orientação agora vem do header com o `rules_file` correto).

- [ ] **Step 12.4: Pipeline passa o contexto**

Em `backend/src/services/pipeline_service.py`, dentro de `run_pipeline`, logo após `base_branch = project.base_branch or "main"`:

```python
        stage_context = {
            "project_name": project.name,
            "objective": getattr(project, "objective", None),
            "rules_file": project.rules_file or "AGENTS.md",
            "requested_by": getattr(card, "requested_by", None),
        }
```

No laço principal, trocar `extra: dict = {}` por `extra: dict = {"context": stage_context}`.
No fix-loop, trocar `{"findings": f}` por `{"findings": f, "context": stage_context}`.

- [ ] **Step 12.5: Alinhar o contrato dos .md do DevKit ao que o backend envia**

1. `devkit/.claude/agents/sismais-dev-planner.md` — substituir a linha `Você recebe: caminho do run, \`spec.md\`, decisões do clarifier, e o \`rulesFile\`.` por:

```
Você recebe no prompt: a tarefa (título + descrição do card) e o contexto do projeto (nome, objetivo, solicitante e o arquivo de regras a seguir).
```

2. `devkit/.claude/agents/sismais-dev-implementer.md` — substituir `Você recebe: a tarefa (ou a lista de achados/falhas a corrigir), o \`rulesFile\`, e o contexto.` por:

```
Você recebe no prompt: a tarefa (ou a lista de achados/falhas a corrigir) e o contexto do projeto (nome, objetivo, solicitante e o arquivo de regras a seguir).
```

E na linha seguinte, trocar `- Leia o \`rulesFile\` + skills/código relevantes ANTES de editar.` por `- Leia o arquivo de regras indicado no prompt + skills/código relevantes ANTES de editar.`

3. `devkit/.claude/agents/sismais-dev-reviewer.md` — substituir `Você é o "segundo dev". Recebe: o diff (ou a branch), e o \`rulesFile\`. **Não confie em nenhum relato do implementador** — leia o código real.` por:

```
Você é o "segundo dev". Recebe no prompt: o diff e o contexto do projeto (com o arquivo de regras a seguir). **Não confie em nenhum relato do implementador** — leia o código real.
```

E na linha `Avalie contra: o \`rulesFile\`, as skills/docs...`, trocar `o \`rulesFile\`` por `o arquivo de regras do projeto`.

- [ ] **Step 12.6: Run tests to verify they pass**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stage_runner_load.py tests/test_pipeline_service.py -v`
Expected: PASS (todos).

- [ ] **Step 12.7: Commit**

```bash
git add backend/src/services/stage_runner.py backend/src/services/pipeline_service.py devkit/.claude/agents backend/tests/test_stage_runner_load.py backend/tests/test_pipeline_service.py
git commit -m "feat(prompt): contexto do projeto/solicitante no prompt dos estagios + rules_file do projeto (A4)"
```

---

### Task 13 (A4c): campo "Objetivo" no modal de novo projeto

O campo `requestedBy` no modal de card fica DELIBERADAMENTE fora desta onda (entra junto com a simplificação do AddCardModal na onda N6); a API já o aceita (chat e integrações podem usar).

**Files:**
- Modify: `frontend/src/api/projectsRegistry.ts`
- Modify: `frontend/src/components/ProjectSelectorRegistry/ProjectSelectorRegistry.tsx`

- [ ] **Step 13.1: API client**

Em `frontend/src/api/projectsRegistry.ts`:

1. Em `RegistryProject`, adicionar `objective?: string | null;`
2. Em `createProject`, mudar a assinatura e o body:

```typescript
export async function createProject(input: { name: string; path: string; objective?: string; workflowId?: string }): Promise<RegistryProject> {
  const r = await fetch(base(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: input.name,
      path: input.path,
      objective: input.objective || undefined,
      workflowId: input.workflowId ?? 'dev',
    }),
  });
```

- [ ] **Step 13.2: Campo no modal**

Em `frontend/src/components/ProjectSelectorRegistry/ProjectSelectorRegistry.tsx`:

1. Novo estado após `path`: `const [objective, setObjective] = useState('');`
2. Em `handleCancel` e no sucesso de `handleCreate`, adicionar `setObjective('');` junto dos resets existentes.
3. Em `handleCreate`, trocar a chamada por:

```tsx
      const project = await createProject({
        name: name.trim(),
        path: path.trim(),
        objective: objective.trim() || undefined,
      });
```

4. No `modalBody`, após o label "Caminho local", adicionar:

```tsx
              <label className={styles.fieldLabel}>
                Objetivo (opcional)
                <textarea
                  className={styles.input}
                  rows={2}
                  placeholder="Objetivo de negócio do projeto — os agentes usam isso para calibrar decisões"
                  value={objective}
                  onChange={(e) => setObjective(e.target.value)}
                  disabled={isCreating}
                />
              </label>
```

- [ ] **Step 13.3: Verificar tipos**

Run: `cd frontend && npx tsc --noEmit`
Expected: apenas os erros pré-existentes.

- [ ] **Step 13.4: Commit**

```bash
git add frontend/src/api/projectsRegistry.ts frontend/src/components/ProjectSelectorRegistry/ProjectSelectorRegistry.tsx
git commit -m "feat(painel): campo Objetivo no cadastro de projeto (A4)"
```

---

### Task 14: Suite completa + atualizar docs

**Files:**
- Modify: `docs/ARQUITETURA_E_ESTADO.md`

- [ ] **Step 14.1: Suite completa do backend**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: PASS em tudo exceto o baseline pré-existente do fork (`test_project_manager.py` / `test_test_result_analyzer.py`). Qualquer outra falha: corrigir antes de seguir.

- [ ] **Step 14.2: Gate do frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: apenas os ~7 erros pré-existentes `Cannot find namespace 'NodeJS'`.

- [ ] **Step 14.3: Atualizar `docs/ARQUITETURA_E_ESTADO.md`**

Adicionar uma seção após "Projeto = escopo do app":

```markdown
### Onda "Agora" da revisão estratégica (A1–A6) — feito 2026-07-09
- **Robustez (A1):** try/except de topo em `run_pipeline` (erro interno → pausa) + done-callback nas tasks;
  `startup_recovery.recover_orphan_executions` no boot pausa Executions RUNNING órfãs de restart.
- **Falha-fechada (A2):** review sem JSON parseável re-pede 1x e pausa (nunca aprova); estágio com turno
  vazio pausa; snippet anti-parada-prematura apendado ao system prompt de todo estágio
  (`stage_runner.AUTONOMY_SNIPPET`); `build_stage_options` é o ponto único de options (plug futuro de perfis).
- **Pausa visível (A3):** coluna `paused` é a primeira do board (seed do workflow virou **upsert** —
  config-as-code); toast global + contador "aguardando você" no TopNav (WS `card_moved`).
- **Telemetria (A5):** `Execution` ganha tokens/model_used (do `ResultMessage.usage`) + `fix_iterations`;
  expostos em `GET .../execution`; LogsModal mostra custo real do run.
- **Chat (A6):** contexto Kanban dirigido pelo workflow config (inclui paused/validate_ci/ready_to_merge,
  com id do card), atividades escopadas por projeto, bloco "Projeto atual" com projectId + worktrees + APIs
  de histórico no system prompt.
- **Contexto (A4):** `Card.requested_by` + `Project.objective` (light migrations); header do prompt dos
  estágios com projeto/objetivo/solicitante/`rules_file` do projeto (hardcode "AGENTS.md" removido);
  contrato dos `.md` do DevKit alinhado ao que o backend envia.
- Spec de origem: `specs/2026-07-09-revisao-estrategica-plataforma.md` · Plano: `plans/2026-07-09-onda-agora-melhorias.md`.
```

- [ ] **Step 14.4: Commit final**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda Agora (A1-A6) no estado da arquitetura"
```

---

## Fora do escopo desta onda (deliberado)

- **requestedBy no AddCardModal** — entra com a simplificação do modal (onda N6).
- **Smoke real no spike-loop-test** — gasta Max; rodar só quando o usuário pedir (os testes desta onda são unitários).
- **Ondas N1–N6** — planos próprios, escritos após esta onda mergear (N1 constrói sobre `build_stage_options` da Task 5; N5 sobre a telemetria da Task 8).

## Self-review (feito na escrita)

- **Cobertura:** A1 = Tasks 1–2 · A2 = Tasks 3–5 · A3 = Tasks 6–7 · A5 = Tasks 8–9 · A6 = Task 10 · A4 = Tasks 11–13. Ordem do usuário respeitada (A1, A2, A3, A5, A6, A4).
- **Consistência de nomes:** `parse_review_findings_strict` (Tasks 3), `build_stage_options`/`AUTONOMY_SNIPPET` (Task 5), `StageResult.usage` (Task 8), `recover_orphan_executions` (Task 2), `persist_run_stats` (Task 8), `stage_context` (Task 12) — cada símbolo definido antes de ser usado.
- **Interações entre tasks:** Task 4 (texto vazio) roda ANTES do parse do review da Task 3 no fluxo — review vazio pausa direto sem re-pedido (ok, determinístico). Task 8 move `iteration`/`plan_text` para antes de `finish_pause` — exigido pelo `persist_run_stats`. Task 12 depende dos campos da Task 11.
