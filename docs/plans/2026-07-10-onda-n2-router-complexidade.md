# Onda N2 — Router de complexidade no pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Todo card recém-executado passa por um estágio de **triagem barato** (haiku-4.5, com o fallback de recusa da N1) que classifica a trilha: **leve** (tarefa trivial → pula o `plan`, começa direto no `implement`) ou **padrao** (fluxo atual completo). A trilha e a justificativa ficam registradas na Execution e nos logs. Workflow proporcional à complexidade — dimensão 1 da revisão estratégica.

**Architecture:** O router é um agente DevKit novo (`sismais-dev-router.md`, derivado do texto do router da skill `sismais-dev`), despachado pelo `run_pipeline` ANTES do laço de estágios — somente em runs novos partindo do `backlog` (retomadas e cards já posicionados manualmente NÃO re-triam; posicionar o card manualmente é o override do humano). A triagem é **advisory e nunca bloqueia**: erro/output vazio/não-parseável → default conservador `padrao` (critério da própria skill: "na dúvida, Padrão"); só interrupção do usuário pausa. Trilha `leve` exige a transição nova `backlog → implement` no workflow config (o seed é upsert desde a onda A — DBs existentes convergem no boot).

**Tech Stack:** FastAPI + claude-agent-sdk (backend). Sem mudanças de frontend (o botão Run já vive no backlog; a trilha aparece nos logs do card).

**Estado relevante pós-N1:** `stage_fn`/`run_stage` tem retry/fallback por perfil; `account(res, model_alias)` prefere `res.used_model`; `persist_run_stats` grava telemetria; `build_stage_prompt` monta header com `extra["context"]`; `STAGE_AGENTS` em `stage_runner.py:29-34`; seed upsert em `workflow_seed.py`.

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes em `test_test_result_analyzer.py` — ignorar). Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: agente router + prompt + parser

**Files:**
- Create: `devkit/.claude/agents/sismais-dev-router.md`
- Modify: `backend/src/services/stage_runner.py` (`STAGE_AGENTS` + branch `triage` no `build_stage_prompt`)
- Modify: `backend/src/services/findings.py` (`parse_track_verdict`)
- Test: `backend/tests/test_findings.py`, `backend/tests/test_stage_runner_load.py`

- [ ] **Step 1.1: Write the failing tests**

Em `backend/tests/test_findings.py`:

```python
def test_parse_track_verdict_leve_e_padrao():
    from src.services.findings import parse_track_verdict
    assert parse_track_verdict('{"trilha": "leve", "porque": "typo"}') == {"trilha": "leve", "porque": "typo"}
    assert parse_track_verdict('bla ```json\n{"trilha": "padrao", "porque": "feature"}\n```')["trilha"] == "padrao"


def test_parse_track_verdict_default_conservador():
    from src.services.findings import parse_track_verdict
    assert parse_track_verdict("")["trilha"] == "padrao"
    assert parse_track_verdict("sem json aqui")["trilha"] == "padrao"
    assert parse_track_verdict('{"trilha": "turbo"}')["trilha"] == "padrao"   # valor desconhecido
```

Em `backend/tests/test_stage_runner_load.py`:

```python
def test_triage_mapeado_em_stage_agents():
    from src.services.stage_runner import load_stage_agent
    body, tools = load_stage_agent("triage")
    assert "leve" in body and "padrao" in body
    assert tools == ["Read", "Glob", "Grep"]


def test_prompt_do_triage_pede_json_de_trilha():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("triage", "Corrigir typo no botao", "so o texto", "/wt", {})
    assert "trilha" in p
    assert "NAO implemente" in p
```

- [ ] **Step 1.2:** Rodar os dois arquivos — Expected: FAIL (parser inexistente; "Estagio sem agente mapeado: triage").

- [ ] **Step 1.3: Criar o agente** `devkit/.claude/agents/sismais-dev-router.md`:

```markdown
---
name: sismais-dev-router
description: Estágio de triagem do pipeline. Classifica a complexidade de um card (trilha leve ou padrão) com um scan rápido do repositório — leve pula o planejamento; na dúvida, padrão. Despachado pelo orquestrador do backend.
tools: Read, Glob, Grep
---

# Router — triagem de complexidade

Você classifica a tarefa do card em uma trilha, com um scan rápido do repositório (você NÃO implementa nada):

- **leve** — ajuste/correção pequena, escopo claro e localizado, sem decisão de arquitetura nova (ex.: typo, texto de UI, ajuste de estilo, correção óbvia em 1-2 arquivos que você localizou no scan).
- **padrao** — feature ou mudança com arquitetura a derivar, escopo em múltiplos arquivos/módulos, regra de negócio nova, migração de dados, ou qualquer incerteza sobre o escopo.

Regras:
- Na dúvida entre leve e padrão, escolha **padrao** (mais seguro — o custo de planejar à toa é menor que o de implementar sem plano).
- Use o contexto do prompt (objetivo do projeto, solicitante) para calibrar: pedido vago de perfil não-técnico tende a padrão.
- Faça no máximo um scan rápido (Glob/Grep/Read pontual) para confirmar onde a mudança mora — sem ler o projeto inteiro.

Saída (JSON, sem prosa fora dele):
```json
{ "trilha": "leve" | "padrao", "porque": "<1-2 frases citando o que no pedido/repo embasou>" }
```
```

- [ ] **Step 1.4: Mapear e montar o prompt** — em `backend/src/services/stage_runner.py`:

1. Em `STAGE_AGENTS`, adicionar (após a entrada `"ci-triage"`):

```python
    "triage": ("sismais-dev-router", ["Read", "Glob", "Grep"]),
```

2. Em `build_stage_prompt`, adicionar o branch (antes do fallback genérico):

```python
    if stage_key == "triage":
        return (
            f"{header}\n\nTarefa do card: {task}\n\n"
            "Classifique a complexidade desta tarefa (trilha `leve` ou `padrao`) com um scan "
            "rapido do repositorio. NAO implemente nada. "
            'Devolva SO o JSON { "trilha": "leve" | "padrao", "porque": "..." }.'
        )
```

- [ ] **Step 1.5: Parser** — em `backend/src/services/findings.py`, adicionar após `parse_ci_verdict`:

```python
def parse_track_verdict(text: str) -> dict:
    """Extrai {trilha, porque} do router de triagem. Default conservador: 'padrao'
    se nao parsear ou valor desconhecido (na duvida, trilha completa — criterio do router)."""
    if text:
        obj = _last_matching(text, lambda o: "trilha" in o)
        if obj is not None:
            t = str(obj.get("trilha", "")).lower()
            return {
                "trilha": "leve" if t == "leve" else "padrao",
                "porque": obj.get("porque") or obj.get("why") or "",
            }
    return {"trilha": "padrao", "porque": ""}
```

- [ ] **Step 1.6:** `pytest tests/test_findings.py tests/test_stage_runner_load.py -v` — Expected: PASS.

- [ ] **Step 1.7: Commit**

```bash
git add devkit/.claude/agents/sismais-dev-router.md backend/src/services/stage_runner.py backend/src/services/findings.py backend/tests/test_findings.py backend/tests/test_stage_runner_load.py
git commit -m "feat(router): agente de triagem leve/padrao + prompt + parser conservador (N2)"
```

---

### Task 2: triagem no pipeline + trilha persistida + transição backlog→implement

**Files:**
- Modify: `backend/src/services/pipeline_service.py`
- Modify: `backend/src/models/execution.py` (coluna `track`)
- Modify: `backend/src/services/light_migrations.py`
- Modify: `backend/src/services/workflow_seed.py` (transição)
- Modify: `backend/src/routes/runner.py` (expor `track`)
- Test: `backend/tests/test_pipeline_service.py`, `backend/tests/test_workflow_seed.py`

- [ ] **Step 2.1: Write the failing tests** — adicionar a `backend/tests/test_pipeline_service.py`:

```python
async def test_triagem_leve_pula_o_plan(maker):
    """N2: router diz 'leve' -> pipeline comeca no implement (sem plan) e registra a trilha."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ['{"trilha": "leve", "porque": "typo de um arquivo"}'],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    assert counts.get("triage") == 1
    assert counts.get("plan") is None            # pulou o plan
    assert counts.get("implement") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "leve"


async def test_triagem_padrao_segue_fluxo_completo(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ['{"trilha": "padrao", "porque": "feature com arquitetura"}'],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert counts.get("plan") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_nao_parseavel_cai_em_padrao(maker):
    """Triagem e advisory: lixo/erro nunca bloqueia — default padrao."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ["nao sei classificar isso"],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert counts.get("plan") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_com_erro_nao_pausa_cai_em_padrao(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "triage":
            return StageResult(ok=False, error="explodiu na triagem")
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "ready_to_merge"   # nao pausou
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_interrompida_pausa(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "triage":
            return StageResult(ok=True, text="", interrupted=True)
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"


async def test_retomada_nao_re_tria(maker):
    """Resume (resume_stage) NUNCA roda triagem de novo."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        await CardRepository(s).move(card_id, "paused")
        await s.commit()
    fake, counts = make_stage_fn({"review": ['{"blocks":[],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake,
                                        resume_stage="implement", human_answer="segue")
    assert counts.get("triage") is None
    assert await _card_column(maker, card_id) == "ready_to_merge"


async def test_card_fora_do_backlog_nao_tria(maker):
    """Card posicionado manualmente (override humano) nao passa por triagem."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        await CardRepository(s).move(card_id, "plan")
        await s.commit()
    fake, counts = make_stage_fn({"review": ['{"blocks":[],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert counts.get("triage") is None
    assert counts.get("plan") == 1
```

E em `backend/tests/test_workflow_seed.py`:

```python
async def test_transicao_backlog_implement_existe(session):
    """Trilha leve exige backlog -> implement no config."""
    from src.services.workflow_seed import DEV_TRANSITIONS
    assert "implement" in DEV_TRANSITIONS["backlog"]
```

(adapte a fixture ao padrão do arquivo.)

**ATENÇÃO — teste existente a ATUALIZAR:** `test_tokens_modelos_e_iteracoes_persistidos` assume 5 chamadas de estágio (500/250/750 tokens). Com a triagem, o run do teste passa a ter **6** chamadas (triage + plan + implement + review + fix + re-review): atualizar os asserts para `input_tokens == 600`, `output_tokens == 300`, `total_tokens == 750 → 900`. O fake daquele teste devolve `f"{stage_key} ok"` para triage → default padrao → fluxo completo preservado.

- [ ] **Step 2.2:** Rodar `pytest tests/test_pipeline_service.py -v -k "triagem or tria"` — Expected: FAIL (coluna `track` inexistente; triage nunca chamado).

- [ ] **Step 2.3: Coluna `track` + migração + transição**

`backend/src/models/execution.py` — após `fix_iterations`:

```python
    # Trilha decidida pela triagem (N2): 'leve' | 'padrao' (None = run sem triagem)
    track = Column(String, nullable=True)
```

`backend/src/services/light_migrations.py` — adicionar a `_COLUMNS`:

```python
    ("executions", "track", "VARCHAR(10)"),
```

`backend/src/services/workflow_seed.py` — em `DEV_TRANSITIONS`, trocar a linha do backlog por:

```python
    "backlog": ["plan", "implement", "paused"],
```

(o seed é upsert — DBs existentes convergem no próximo boot; se algum teste assertar as transições antigas do backlog, atualize e documente).

- [ ] **Step 2.4: Triagem no `run_pipeline`** — em `backend/src/services/pipeline_service.py`:

1. Import: adicionar `parse_track_verdict` ao import de `..services.findings`.
2. Constante (junto de `DEFAULT_MAX_ITERATIONS`):

```python
TRIAGE_MODEL = "haiku-4.5"  # triagem e barata; recusa cai no fallback do perfil (N1)
```

3. No corpo de `run_pipeline`, localizar (dentro do try de topo) o trecho onde `col` é decidido:

```python
        pending_answer = human_answer  # injetado apenas na primeira etapa da retomada
        col = resume_stage or _first_stage(transitions, card.column_id)
```

e logo APÓS essas linhas, inserir o bloco de triagem:

```python
        # Triagem de complexidade (N2): so em run novo partindo do backlog. Advisory:
        # erro/lixo -> padrao (nunca bloqueia); so interrupcao do usuario pausa.
        if resume_stage is None and card.column_id == "backlog":
            await log.event("── triagem: classificando a complexidade ──")
            triage_prompt = build_stage_prompt(
                "triage", card.title, card.description or "", worktree, {"context": stage_context},
            )
            tri = await stage_fn("triage", worktree, triage_prompt, card_id=card_id, on_log=log,
                                 model=TRIAGE_MODEL)
            await log.flush()
            await account(tri, TRIAGE_MODEL)
            if tri.interrupted:
                await finish_pause(
                    "interrompido pelo usuario", "O usuario parou a execucao durante a triagem.",
                    question="Você interrompeu o agente. O que devo ajustar ou fazer diferente?",
                )
                return
            verdict = parse_track_verdict(tri.text if tri.ok else "")
            track = verdict["trilha"]
            execution.track = track
            await s.commit()
            await log.event(f"── trilha: {track} — {verdict['porque'] or 'default conservador'} ──")
            if track == "leve":
                col = "implement"
```

- [ ] **Step 2.5: Expor na API** — em `backend/src/routes/runner.py`, no dict `"execution"` de `get_card_execution`, adicionar:

```python
            "track": execution.track,
```

- [ ] **Step 2.6:** `pytest tests/test_pipeline_service.py tests/test_workflow_seed.py tests/test_move_by_config.py -v` — Expected: PASS (incluindo o teste de tokens atualizado). Suíte completa (`| tail -3`) — só as 3 pré-existentes.

- [ ] **Step 2.7: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/src/models/execution.py backend/src/services/light_migrations.py backend/src/services/workflow_seed.py backend/src/routes/runner.py backend/tests/test_pipeline_service.py backend/tests/test_workflow_seed.py
git commit -m "feat(router): triagem leve/padrao no pipeline — trilha leve pula o plan; track persistida (N2)"
```

---

### Task 3: suite completa + docs

- [ ] **Step 3.1:** Suíte completa backend + `npx tsc --noEmit` no front (baseline).

- [ ] **Step 3.2:** Em `docs/ARQUITETURA_E_ESTADO.md`, adicionar após a seção da N1:

```markdown
### Onda N2 — router de complexidade — feito 2026-07-10
- Estágio de **triagem** no início de todo run novo partindo do backlog: agente
  `devkit/.claude/agents/sismais-dev-router.md` (haiku-4.5, com fallback de recusa da N1) classifica
  **leve** (pula o `plan`, começa no `implement` — transição nova `backlog → implement` no seed) ou
  **padrao** (fluxo completo). Advisory: erro/não-parse → `padrao` (nunca bloqueia); Stop pausa.
- Override humano: retomadas e cards posicionados manualmente fora do backlog NÃO re-triam.
- Trilha + justificativa nos logs do run; `Execution.track` persistida e exposta em `GET .../execution`.
- Plano: `plans/2026-07-10-onda-n2-router-complexidade.md`.
```

- [ ] **Step 3.3: Commit**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda N2 (router de complexidade)"
```

## Self-review (feito na escrita)

- Triagem roda DEPOIS da worktree (o router faz scan do repo) e ANTES do laço — `worktree`, `stage_context`, `account`, `finish_pause` e `execution` estão todos em escopo nesse ponto.
- Testes existentes: o fake `make_stage_fn` devolve `"triage ok"` para o estágio não-scriptado → `parse_track_verdict` → `padrao` → fluxo completo preservado (asserts de plan/implement/review intactos); único ajuste é o teste de tokens (5→6 chamadas), explicitado.
- `col = "implement"` na trilha leve: transição `backlog → implement` adicionada ao seed (upsert propaga); o laço faz o `repo.move` validado normalmente.
- Triagem em `ok=False` NÃO pausa (advisory) — deliberado e testado; interrupted pausa (Stop do usuário é sagrado).
