# Onda N4 — Dispatcher dirigido pelo config do workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O motor do pipeline passa a honrar o config que já persiste: qual agente roda em cada coluna vem do **`agentKey`** das colunas do workflow (hoje gravado e ignorado), a convenção de pausa vem do flag **`isPausedState`** (hoje `PAUSE_COLUMNS` hardcoded), e os agentes DevKit órfãos (**specifier/clarifier/tasker**) ficam plugáveis como colunas. Um workflow novo com coluna `spec` passa a EXECUTAR — dimensões 1 e 9 da revisão estratégica. O workflow `dev` seedado não muda de comportamento.

**Architecture:** Dispatch em 2 níveis, ambos config-driven: (1) a coluna → `agentKey` (lido de `workflow.columns`); (2) o `agentKey` → comportamento: `None` = fronteira (move e para); `"validate-ci"` = handler git/gh (`run_validate_ci`); `"implement"` e `"review"` mantêm suas semânticas especiais (commit + needs_human; fix-loop); qualquer OUTRO agentKey mapeado em `STAGE_AGENTS` roda como **estágio genérico de planejamento**: executa o agente, pausa em `pendingQuestions`/`needs_human`, e ACUMULA o texto de saída num contexto encadeado que chega ao `implement` (generaliza o `plan_text` atual — `spec → clarify → plan` viram uma cadeia). `CardRepository` ganha `_get_workflow_for_card` (columns+transitions com fallback dev). O laço do pipeline deixa de consultar `_AGENT_STAGES` hardcoded.

**Fallback e segurança:** coluna com agentKey desconhecido (sem entrada em `STAGE_AGENTS`) → pausa com motivo claro (config inválido é erro humano, não deve avançar silencioso). Colunas do seed `dev` têm agentKeys `plan`/`implement`/`review`/`validate-ci` — comportamento idêntico ao atual (o agentKey `plan` roda como estágio genérico, que é exatamente a semântica atual do plan).

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes em `test_test_result_analyzer.py` — ignorar). Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

**Estado relevante (pós-N2):** `_AGENT_STAGES = ("plan","implement","review")` e `_pipeline_handles` em `pipeline_service.py:~47-54`; `_STAGE_MODEL_FIELD` por coluna; triagem N2 antes do laço; `STAGE_AGENTS` em `stage_runner.py` com plan/implement/review/ci-triage/triage; `workflow_rules.PAUSE_COLUMNS = {"paused"}`; seed com `agentKey` por coluna (`"validate-ci"` com hífen na coluna `validate_ci`); `repo._get_transitions_for_card` resolve só transitions.

---

### Task 1: resolução de workflow completo por card + regras de pausa via config

**Files:**
- Modify: `backend/src/repositories/card_repository.py` (`_get_workflow_for_card`)
- Modify: `backend/src/services/workflow_rules.py` (`pause_columns_from`, `next_active_column` config-aware)
- Test: `backend/tests/test_workflow_rules.py`, `backend/tests/test_card_repository.py`

- [ ] **Step 1.1: Write the failing tests**

Em `backend/tests/test_workflow_rules.py`:

```python
def test_pause_columns_from_config():
    from src.services.workflow_rules import pause_columns_from
    cols = [
        {"key": "fila", "isPausedState": False},
        {"key": "esperando_humano", "isPausedState": True},
        {"key": "done"},
    ]
    assert pause_columns_from(cols) == {"esperando_humano"}


def test_pause_columns_from_vazio_usa_default():
    from src.services.workflow_rules import pause_columns_from
    assert pause_columns_from([]) == {"paused"}
    assert pause_columns_from(None) == {"paused"}


def test_next_active_column_com_pausa_custom():
    from src.services.workflow_rules import next_active_column
    transitions = {"a": ["esperando_humano", "b"]}
    assert next_active_column(transitions, "a", pause_cols={"esperando_humano"}) == "b"
```

Em `backend/tests/test_card_repository.py` (adapte à fixture do arquivo):

```python
async def test_get_workflow_for_card_com_fallback_dev(async_session):
    """Sem workflow row, devolve colunas+transitions do seed dev (fallback)."""
    from src.repositories.card_repository import CardRepository
    from src.schemas.card import CardCreate
    from src.services.workflow_seed import DEV_COLUMNS, DEV_TRANSITIONS
    repo = CardRepository(async_session)
    card = await repo.create(CardCreate(title="T"), project_id=None)
    columns, transitions = await repo._get_workflow_for_card(card)
    assert columns == DEV_COLUMNS
    assert transitions == DEV_TRANSITIONS
```

- [ ] **Step 1.2:** Rodar — Expected: FAIL (funções inexistentes).

- [ ] **Step 1.3: Implementar**

`backend/src/services/workflow_rules.py` — manter `PAUSE_COLUMNS` e `is_valid_transition` como estão; adicionar `pause_columns_from` e estender `next_active_column` com parâmetro opcional:

```python
def pause_columns_from(columns) -> set:
    """Colunas de pausa derivadas do config (flag isPausedState). Fallback: {'paused'}."""
    if not columns:
        return set(PAUSE_COLUMNS)
    found = {c["key"] for c in columns if c.get("isPausedState")}
    return found or set(PAUSE_COLUMNS)
```

Em `next_active_column`, mudar a assinatura para `next_active_column(transitions, current, pause_cols=None)` e usar `pause_cols = pause_cols or PAUSE_COLUMNS` no lugar da constante no corpo (chamadas existentes sem o argumento mantêm o comportamento).

`backend/src/repositories/card_repository.py` — ao lado de `_get_transitions_for_card` (leia o método atual e siga o mesmo padrão de resolução projeto→workflow→fallback), adicionar:

```python
    async def _get_workflow_for_card(self, card) -> tuple[list, dict]:
        """Colunas+transições do workflow do projeto do card (fallback: seed dev)."""
        from ..services.workflow_seed import DEV_COLUMNS, DEV_TRANSITIONS
        workflow = await self._resolve_workflow_row(card)
        if workflow is None:
            return DEV_COLUMNS, DEV_TRANSITIONS
        return workflow.columns or DEV_COLUMNS, workflow.transitions or DEV_TRANSITIONS
```

Se `_get_transitions_for_card` tiver a resolução inline (sem um `_resolve_workflow_row`), extraia o helper `_resolve_workflow_row(card) -> Workflow | None` do código existente e faça `_get_transitions_for_card` delegar a ele também (sem mudar seu comportamento).

- [ ] **Step 1.4:** `pytest tests/test_workflow_rules.py tests/test_card_repository.py tests/test_next_active_column.py tests/test_move_by_config.py -v` — Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add backend/src/services/workflow_rules.py backend/src/repositories/card_repository.py backend/tests/test_workflow_rules.py backend/tests/test_card_repository.py
git commit -m "feat(workflow): resolucao de workflow completo por card + pausa via isPausedState do config (N4)"
```

---

### Task 2: agentes SDD órfãos plugáveis + prompt genérico de estágio

**Files:**
- Modify: `backend/src/services/stage_runner.py` (`STAGE_AGENTS` + prompt genérico)
- Test: `backend/tests/test_stage_runner_load.py`

- [ ] **Step 2.1: Write the failing tests** — em `backend/tests/test_stage_runner_load.py`:

```python
def test_agentes_sdd_mapeados():
    from src.services.stage_runner import load_stage_agent
    for key, filename_hint in (("specify", "specifier"), ("clarify", "clarifier"), ("tasks", "tasker")):
        body, tools = load_stage_agent(key)
        assert body.strip(), key
        assert tools == ["Read", "Glob", "Grep"], key


def test_prompt_generico_encadeia_saidas_anteriores():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("specify", "Feature X", "detalhe", "/wt",
                           {"chain": "SAIDA-DO-ESTAGIO-ANTERIOR"})
    assert "Feature X" in p
    assert "SAIDA-DO-ESTAGIO-ANTERIOR" in p
    assert "pendingQuestions" in p          # valvula de escalacao padrao dos estagios genericos
```

- [ ] **Step 2.2:** Rodar — Expected: FAIL.

- [ ] **Step 2.3: Implementar** — em `backend/src/services/stage_runner.py`:

1. Em `STAGE_AGENTS`, adicionar (após `"triage"`):

```python
    # Estagios SDD genericos (N4): plugaveis via agentKey nas colunas de workflows custom
    "specify": ("sismais-dev-specifier", ["Read", "Glob", "Grep"]),
    "clarify": ("sismais-dev-clarifier", ["Read", "Glob", "Grep"]),
    "tasks": ("sismais-dev-tasker", ["Read", "Glob", "Grep"]),
```

2. Em `build_stage_prompt`, substituir o fallback genérico final (`return f"{header}\n\nTarefa: {task}"`) por:

```python
    # Estagio generico (colunas custom / SDD): o papel vem do system prompt (.md do agente);
    # a saida do(s) estagio(s) anterior(es) chega encadeada como material de referencia.
    chain = extra.get("chain")
    chain_block = f"\n\nMaterial dos estagios anteriores:\n{chain}\n" if chain else ""
    return (
        f"{header}\n\nTarefa: {task}{answer_block}{chain_block}\n\n"
        "Execute o SEU estagio conforme suas instrucoes e responda com o resultado em markdown. "
        "Se uma decisao nao tiver base no projeto, devolva tambem um bloco JSON "
        '`{ "pendingQuestions": [ { "question": "...", "context": "..." } ] }` ao final.'
    )
```

(`answer_block` já existe na função — o estágio genérico também recebe resposta humana de retomada.)

- [ ] **Step 2.4:** `pytest tests/test_stage_runner_load.py -v` — Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add backend/src/services/stage_runner.py backend/tests/test_stage_runner_load.py
git commit -m "feat(stage): agentes SDD (specifier/clarifier/tasker) plugaveis + prompt generico encadeado (N4)"
```

---

### Task 3: laço do pipeline dirigido pelo agentKey do config

**Files:**
- Modify: `backend/src/services/pipeline_service.py`
- Test: `backend/tests/test_pipeline_service.py`

- [ ] **Step 3.1: Write the failing tests** — adicionar a `backend/tests/test_pipeline_service.py`:

```python
async def _make_project_card_com_workflow(maker, columns, transitions, workflow_id="custom"):
    """Projeto com workflow CUSTOM + card. Reusa o padrao de _make_project_card."""
    from src.models.workflow import Workflow
    async with maker() as s:
        s.add(Workflow(id=workflow_id, name="Custom", columns=columns, transitions=transitions))
        s.add(Project(id="p2", name="proj2", path="/tmp/proj2", workflow_id=workflow_id,
                      base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa Y"), project_id="p2")
        await s.commit()
        return card.id


_SDD_COLUMNS = [
    {"key": "backlog", "label": "Backlog", "order": 0, "agentKey": None, "isPausedState": False, "isTerminal": False},
    {"key": "spec", "label": "Spec", "order": 1, "agentKey": "specify", "isPausedState": False, "isTerminal": False},
    {"key": "implement", "label": "Implement", "order": 2, "agentKey": "implement", "isPausedState": False, "isTerminal": False},
    {"key": "review", "label": "Review", "order": 3, "agentKey": "review", "isPausedState": False, "isTerminal": False},
    {"key": "entregue", "label": "Entregue", "order": 4, "agentKey": None, "isPausedState": False, "isTerminal": True},
    {"key": "paused", "label": "Paused", "order": 5, "agentKey": None, "isPausedState": True, "isTerminal": False},
]
_SDD_TRANSITIONS = {
    "backlog": ["spec", "paused"],
    "spec": ["implement", "paused"],
    "implement": ["review", "paused"],
    "review": ["entregue", "implement", "paused"],
    "entregue": [],
    "paused": ["spec", "implement", "review"],
}


async def test_workflow_custom_executa_coluna_spec(maker):
    """N4: coluna 'spec' (agentKey specify) EXECUTA e encadeia a saida para o implement."""
    card_id = await _make_project_card_com_workflow(maker, _SDD_COLUMNS, _SDD_TRANSITIONS)
    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        if stage_key == "review":
            return StageResult(ok=True, text='{"blocks":[],"fixNow":[]}')
        if stage_key == "specify":
            return StageResult(ok=True, text="SPEC-GERADA-PELO-SPECIFIER")
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)

    assert "specify" in seen                                   # a coluna spec executou
    assert "SPEC-GERADA-PELO-SPECIFIER" in seen["implement"][0]  # saida encadeada ao implement
    assert await _card_column(maker, card_id) == "entregue"    # fronteira custom (agentKey None)


async def test_workflow_custom_pausa_em_pending_questions_de_estagio_generico(maker):
    card_id = await _make_project_card_com_workflow(maker, _SDD_COLUMNS, _SDD_TRANSITIONS,
                                                    workflow_id="custom2")
    fake, counts = make_stage_fn({
        "specify": ['{"pendingQuestions":[{"question":"qual regra de negocio?"}]}'],
    })
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("implement") is None


async def test_agentkey_desconhecido_pausa_com_motivo(maker):
    cols = [
        {"key": "backlog", "label": "B", "order": 0, "agentKey": None, "isPausedState": False, "isTerminal": False},
        {"key": "magica", "label": "M", "order": 1, "agentKey": "inexistente", "isPausedState": False, "isTerminal": False},
        {"key": "paused", "label": "P", "order": 2, "agentKey": None, "isPausedState": True, "isTerminal": False},
    ]
    trans = {"backlog": ["magica", "paused"], "magica": ["paused"], "paused": ["magica"]}
    card_id = await _make_project_card_com_workflow(maker, cols, trans, workflow_id="custom3")
    fake, counts = make_stage_fn({})
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert "agentKey" in (ex.workflow_error or "")
```

NOTAS para os testes: a triagem N2 só roda a partir do `backlog` — nos workflows custom acima o card também nasce no backlog, então o fake recebe uma chamada `triage` (default `padrao` — inofensivo; para o custom3 o `make_stage_fn` default devolve "triage ok"). A trilha `leve` do triage só desvia quando `"implement" in transitions.get("backlog", [])` — falso nos customs acima.

- [ ] **Step 3.2:** Rodar `-k "custom or agentkey"` — Expected: FAIL (coluna spec não executa hoje: vira fronteira e o card para nela).

- [ ] **Step 3.3: Implementar o dispatch por agentKey** — em `backend/src/services/pipeline_service.py`:

1. Substituir as definições hardcoded:

```python
# Colunas que o pipeline executa: estagios de agente + validate_ci (git/gh, tratado a parte).
_AGENT_STAGES = ("plan", "implement", "review")

# coluna -> campo do card com o alias de modelo escolhido para a etapa.
_STAGE_MODEL_FIELD = {"plan": "model_plan", "implement": "model_implement", "review": "model_review"}


def _pipeline_handles(col: Optional[str]) -> bool:
    return col in _AGENT_STAGES or col == "validate_ci"
```

por:

```python
# agentKey -> campo do card com o alias de modelo escolhido para a etapa.
# Estagios SDD genericos usam o modelo do plan (mesma natureza: planejamento read-only).
_STAGE_MODEL_FIELD = {
    "plan": "model_plan", "specify": "model_plan", "clarify": "model_plan", "tasks": "model_plan",
    "implement": "model_implement", "review": "model_review",
}

# agentKey do handler git/gh (nao e um agente): normaliza hifen/underscore do config.
_VALIDATE_CI_KEYS = {"validate-ci", "validate_ci"}


def _agent_key_for(col: Optional[str], columns: list) -> Optional[str]:
    """agentKey da coluna no config (None = fronteira/manual)."""
    for c in columns or []:
        if c.get("key") == col:
            return c.get("agentKey")
    return None


def _pipeline_handles(col: Optional[str], columns: list) -> bool:
    return bool(col) and _agent_key_for(col, columns) is not None
```

2. `stage_model_for_column(col, card)` vira `stage_model_for_agent(agent_key, card)` (mesmo corpo, consultando `_STAGE_MODEL_FIELD` pelo agentKey). Manter um alias de compatibilidade `stage_model_for_column = stage_model_for_agent` se algum teste o importar (verifique por grep; atualize os testes se preferir).

3. `_first_stage(transitions, current)` ganha o parâmetro `columns`: `def _first_stage(transitions, current, columns)` usando `_pipeline_handles(current, columns)` e repassando `pause_columns_from(columns)` ao `next_active_column`.

4. Em `run_pipeline`:
   - Trocar `transitions = await repo._get_transitions_for_card(card)` por `columns, transitions = await repo._get_workflow_for_card(card)` e definir `pause_cols = pause_columns_from(columns)` (import de `workflow_rules`). TODA chamada de `next_active_column(transitions, X)` no arquivo passa a `next_active_column(transitions, X, pause_cols)`.
   - O laço `while col and _pipeline_handles(col):` vira `while col and _pipeline_handles(col, columns):` e o corpo passa a despachar por agentKey:

```python
            agent_key = _agent_key_for(col, columns)
```

   - O branch `if col == "validate_ci":` vira `if agent_key in _VALIDATE_CI_KEYS:` (corpo inalterado; o `next_active_column(transitions, "validate_ci")` interno vira `next_active_column(transitions, col, pause_cols)`).
   - Guard de agentKey desconhecido, logo após obter `agent_key` (antes de montar prompt):

```python
            if agent_key not in _VALIDATE_CI_KEYS and not has_stage(agent_key):
                await finish_pause(
                    f"coluna {col} com agentKey desconhecido: {agent_key}",
                    "Config do workflow referencia um agente que o backend nao mapeia (STAGE_AGENTS).",
                )
                return
```

   (import `has_stage` de `stage_runner`.)
   - As chamadas `stage_fn(col, ...)` viram `stage_fn(agent_key, ...)` e `build_stage_prompt(col, ...)` vira `build_stage_prompt(agent_key, ...)`; `model=stage_model_for_agent(agent_key, card)`.
   - Pós-processamento por agentKey em vez de por coluna:
     - `elif agent_key == "implement":` (commit + needs_human — corpo atual).
     - `elif agent_key == "review":` (fix-loop — corpo atual; o move do fix-loop continua indo para a COLUNA de implement: use `impl_col = next((c["key"] for c in columns if c.get("agentKey") == "implement"), "implement")` no lugar do literal `"implement"` nos `repo.move`/retorno do fix-loop; os `stage_fn("implement", ...)`/`build_stage_prompt("implement", ...)` do fix-loop continuam usando o agentKey literal `implement`).
     - O branch atual do `plan` (`if col == "plan":`) vira o branch GENÉRICO (else dos três acima): parse `pendingQuestions` → pausa; `detect_needs_human` → pausa; senão ACUMULA a saída:

```python
            else:
                pend = parse_pending_questions(res.text)
                if pend:
                    await finish_pause(f"{agent_key}: pendencias", res.text[:1500],
                                       question=_format_questions(pend))
                    return
                nh = detect_needs_human(res.text)
                if nh:
                    await finish_pause(f"{agent_key}: needs_human", nh,
                                       question=f"O agente precisa da sua decisao para continuar:\n\n{nh}")
                    return
                chain_parts.append(f"## Saida do estagio {agent_key}\n{res.text}")
                col = next_active_column(transitions, col, pause_cols)
```

     - Substituir a variável `plan_text` por `chain_parts: list[str] = []` (inicializada junto de `iteration`); o `extra` do implement passa a usar `if agent_key == "implement" and chain_parts: extra["plan"] = "\n\n".join(chain_parts)`; estágios genéricos recebem `extra["chain"] = "\n\n".join(chain_parts)` quando não-vazio. (O prompt do implement já usa `extra["plan"]` — inalterado.)
   - A "parada limpa na fronteira" final usa `_pipeline_handles(col, columns)`.

5. A triagem N2 continua como está (roda antes do laço; o gate dela é `card.column_id == "backlog"`).

- [ ] **Step 3.4:** `pytest tests/test_pipeline_service.py -v` — Expected: PASS em TODOS (os testes do fluxo dev provam zero regressão: o seed tem agentKeys plan/implement/review/validate-ci, então o dispatch por agentKey reproduz o comportamento atual). Rodar também `tests/test_pipeline_model_wiring.py tests/test_validate_ci.py` e a suíte completa (`| tail -3`).

- [ ] **Step 3.5: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipeline): dispatch por agentKey do workflow config — colunas custom executam (N4)"
```

---

### Task 4: suite completa + docs

- [ ] **Step 4.1:** Suíte completa backend + tsc front (baselines).

- [ ] **Step 4.2:** Em `docs/ARQUITETURA_E_ESTADO.md`, após a seção da N2:

```markdown
### Onda N4 — dispatcher dirigido pelo config — feito 2026-07-10
- O laço do pipeline despacha pelo **`agentKey`** das colunas do workflow (antes: `_AGENT_STAGES`
  hardcoded — colunas novas não executavam). `None` = fronteira; `validate-ci` = handler git/gh;
  `implement`/`review` mantêm semânticas especiais (commit+needs_human; fix-loop); qualquer outro
  agentKey mapeado roda como **estágio genérico** (pausa em pendingQuestions/needs_human; saída
  **encadeada** ao implement — generaliza o plan_text). agentKey desconhecido → pausa com motivo.
- Pausa via **`isPausedState`** do config (`workflow_rules.pause_columns_from`); `CardRepository.
  _get_workflow_for_card` resolve columns+transitions (fallback dev).
- Agentes SDD órfãos plugáveis: `specify`/`clarify`/`tasks` em `STAGE_AGENTS` + prompt genérico.
  Workflow custom com coluna `spec` **executa** (testado); o `dev` seedado não muda de comportamento.
- Plano: `plans/2026-07-10-onda-n4-dispatcher-config.md`.
```

- [ ] **Step 4.3: Commit**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda N4 (dispatcher config-driven)"
```

## Self-review (feito na escrita)

- Zero regressão no dev: agentKeys do seed (`plan`/`implement`/`review`/`validate-ci`) reproduzem o dispatch atual 1:1 (plan cai no branch genérico, que é a semântica atual do plan; `validate-ci` normalizado pelo set `_VALIDATE_CI_KEYS`).
- O fix-loop move o card para a COLUNA cujo agentKey é implement (resolve por config) — em workflows custom com coluna implement renomeada, funciona; sem coluna implement, `impl_col` default "implement" falha o move → pausa "fix-loop: transicao invalida" (falha-fechada aceitável para config incompleto).
- `chain_parts` substitui `plan_text` — a retomada continua sem persistir a cadeia (limitação pré-existente do plan_text, registrada na revisão estratégica; não piora).
- Testes custom provam: coluna spec executa, encadeia, pausa em pendingQuestions, e agentKey inválido pausa com motivo.
