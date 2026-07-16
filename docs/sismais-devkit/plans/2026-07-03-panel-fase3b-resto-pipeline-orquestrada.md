# Fase 3b-resto — Pipeline orquestrada pelo backend — Plano de Implementação

> **Para workers agênticos:** SUB-SKILL: use subagent-driven-development (ou executing-plans) tarefa a tarefa.
> Spec: `docs/sismais-devkit/specs/2026-07-03-panel-fase3b-resto-pipeline-orquestrada-design.md`.

**Objetivo:** o backend dirige o card por `plan → implement → review` (fix-loop, pause, avanço de coluna), executando
o agente de estágio do DevKit por coluna numa worktree reusada, com logs em streaming pro board.

**Arquitetura:** backend = orquestrador; coluna = estágio; estágio = 1 `query()` do SDK com o `.md` do agente como
system prompt. Estado/logs nas tabelas existentes `executions`/`execution_logs`. Run em background + WS.

**Stack:** FastAPI + SQLAlchemy 2 async + SQLite · `claude-agent-sdk` (auth Max) · React 18 + Vite.

**Ambiente:** Windows/Git Bash. Backend em `backend/` (venv em `venv/Scripts/`). Rodar tudo do dir do backend.
Smoke real **só** em `maiconsaraiva/spike-loop-test`.

---

## Grupo A — Backend (o núcleo; testável por unit + curl/WS antes do front)

### Task A1: `ColumnId` vira `str` (desbloqueia mover pra `paused`/`validate_ci`/`ready_to_merge`)

**Files:** Modify `backend/src/schemas/card.py:29`. Test: `backend/tests/test_column_id_move.py` (novo).

- [ ] Trocar `ColumnId = Literal[...]` por `ColumnId = str`. Manter `ModelType`/`MergeStatus`.
- [ ] Teste: `CardRepository.move` de `review`→`paused` retorna card (transição válida no config dev) e de
      `review`→`done` retorna erro (inválida). Usar workflow `dev` semeado (`seed_dev_workflow`).
- [ ] `import src.models  # noqa: F401` no topo do teste. Rodar: `pytest tests/test_column_id_move.py -v`.
- [ ] Commit: `fix(schema): ColumnId como str (colunas vêm do config) + teste de move p/ paused`.

### Task A2: helpers de git na worktree (`commit_all`, `diff_against_base`)

**Files:** Modify `backend/src/git_workspace.py`. Test: `backend/tests/test_git_workspace_commit.py` (novo, usa um repo git temporário real via `tmp_path`).

- [ ] `async def commit_all(self, worktree_path, message) -> tuple[bool, str]`: `git -C <wt> add -A` então
      `git -C <wt> commit -m <message>`; retorna (ok, stdout/stderr). Se "nothing to commit", ok=True.
- [ ] `async def diff_against_base(self, worktree_path, base_branch) -> str`: `git -C <wt> diff <base>...HEAD`
      (stdout). Vazio se sem diff.
- [ ] Teste: cria repo git em `tmp_path`, commit inicial, worktree, escreve arquivo, `commit_all` → `diff_against_base`
      contém o arquivo. Rodar o teste.
- [ ] Commit: `feat(git): commit_all e diff_against_base na worktree p/ o orquestrador`.

### Task A3: `next_active_column` (sucessora do caminho-feliz no config)

**Files:** Modify `backend/src/services/workflow_rules.py`. Test: `backend/tests/test_next_active_column.py` (novo).

- [ ] `def next_active_column(transitions, current) -> str | None`: retorna o **primeiro** destino de
      `transitions[current]` que **não** é estado de pausa (por convenção, ignorar `"paused"`). `None` se não houver
      (terminal). Assinatura só com `transitions` + `current` (a flag de pausa é o alvo `"paused"` no dev; manter simples).
- [ ] Teste com `DEV_TRANSITIONS`: `backlog→plan`, `plan→implement`, `implement→review`, `review→validate_ci`,
      `ready_to_merge→done`, `done→None`.
- [ ] Commit: `feat(workflow): next_active_column (sucessora do caminho-feliz)`.

### Task A4: parser de achados do reviewer + sinais de pausa

**Files:** Create `backend/src/services/findings.py`. Test: `backend/tests/test_findings.py` (novo).

- [ ] `parse_review_findings(text) -> dict`: acha o **último** bloco `{...}` JSON válido (tolera cercas ```json e prosa
      ao redor); retorna `{"blocks":[], "fixNow":[], "suggestions":[]}` com defaults se ausente/inválido.
- [ ] `parse_pending_questions(text) -> list`: extrai `pendingQuestions` de um JSON no texto (`[]` se ausente).
- [ ] `detect_needs_human(text) -> str | None`: se o texto sinaliza `status: needs_human` (regex tolerante), devolve o
      contexto/linha; senão `None`.
- [ ] Testes: JSON puro; JSON dentro de ```json + prosa; texto sem JSON → defaults; `pendingQuestions` presente/ausente;
      `needs_human` presente/ausente.
- [ ] Commit: `feat(findings): parser de achados/pendências/needs_human do output dos agentes`.

### Task A5: stage runner (carrega o `.md` do agente → system prompt; roda a query)

**Files:** Create `backend/src/services/stage_runner.py`. Test: `backend/tests/test_stage_runner_load.py` (novo).

- [ ] `STAGE_AGENTS = {"plan":("sismais-dev-planner",[R,G,Grep]), "implement":("sismais-dev-implementer",[R,G,Grep,Edit,Write,Bash]), "review":("sismais-dev-reviewer",[R,G,Grep,Bash])}` (constantes de tools como strings do SDK).
- [ ] `load_stage_agent(stage_key) -> tuple[str, list[str]]`: lê `devkit/.claude/agents/<file>.md` (via
      `DEVKIT_AGENTS = runner_service.DEVKIT_CLAUDE / "agents"`), remove o frontmatter YAML (bloco entre `---`),
      retorna (corpo, tools). Erro claro se estágio desconhecido.
- [ ] `@dataclass StageResult{ text, cost_usd, ok, error }`.
- [ ] `async def run_stage(stage_key, worktree, prompt, on_log=None) -> StageResult`: monta
      `ClaudeAgentOptions(cwd=worktree, setting_sources=["project"], system_prompt=<corpo>, allowed_tools=<tools>,
      permission_mode="acceptEdits")`, itera `query()`, coleta `TextBlock.text` (→ on_log) e `total_cost_usd`.
- [ ] Teste (sem SDK): `load_stage_agent("review")` devolve corpo sem `---` e tools == esperado; estágio inválido levanta.
- [ ] Commit: `feat(stage-runner): executa um estágio do DevKit como query focada (agente .md = system prompt)`.

### Task A6: prompts por estágio

**Files:** Modify `backend/src/services/stage_runner.py` (ou `pipeline_service.py`). Test: coberto por A7.

- [ ] `build_stage_prompt(stage_key, title, description, worktree, extra) -> str`:
  - `plan`: "Produza o conteúdo de plan.md para a tarefa e **escreva em `.sismais/plan.md`** na worktree. Tarefa: …".
  - `implement`: tarefa + (se `extra` tiver achados) "Corrija SÓ estes achados: <lista>". Não commitar.
  - `review`: "Revise o diff a seguir e devolva SÓ o JSON de achados.\n<diff>" (o diff vem do orquestrador).
- [ ] Sem teste dedicado (função pura simples; validada em A7).

### Task A7: orquestrador `run_pipeline` (o coração)

**Files:** Create `backend/src/services/pipeline_service.py`. Test: `backend/tests/test_pipeline_service.py` (novo, com `run_stage` **monkeypatchado**).

- [ ] `async def run_pipeline(project_id, card_id, session_maker=async_session_maker, stage_fn=run_stage)`:
  1. Abre sessão própria (`async with session_maker() as s`). Carrega Project + Card. Cria `Execution(card_id,
     status=running, is_active=True)`; guarda `execution_id`.
  2. `wt = await prepare_worktree(project.path, project.base_branch, card_id)`; grava `worktree_path`/`branch_name`
     no card. Se falhar → `_pause`/erro.
  3. Laço a partir da coluna atual: `col = next_active_column(transitions, card.column_id)`; enquanto `col` tem handler
     em `STAGE_AGENTS`:
     - `await _move(s, card, col)` (via `CardRepository.move`; broadcast `card_moved`); log `stage_start`.
     - `prompt = build_stage_prompt(col, …, extra)`; `res = await stage_fn(col, wt.worktree_path, prompt, on_log=_batched_log)`.
     - Desfecho por estágio:
       - `plan`: `pendingQuestions` → `_pause("plan pendências", …)`, **return**. Senão `col = next_active(...)`.
       - `implement`: `needs_human` → `_pause(...)`, return. Senão `commit_all(wt, "wip: <title>")`; `col = next_active(...)`.
       - `review`: `f = parse_review_findings(res.text)`; se `len(blocks)+len(fixNow) > 0`:
         - se `iteration >= maxIterations` → `_pause("não convergiu", achados)`, return.
         - senão: `_move(implement)`; `prompt_fix = build_stage_prompt("implement", …, extra=f)`;
           `run implement`; `commit_all`; `iteration += 1`; `col = "review"` (re-revisa). **continua o laço**.
       - review limpo → `col = next_active(transitions, "review")` (= `validate_ci`, sem handler) → laço **para**.
     - exceção em qualquer estágio → `_pause`/`Execution.status=error`, `notify_complete(error)`, return.
  4. Ao parar limpo em `validate_ci`: `Execution.status=success`, `is_active=False`, `notify_complete(success)`.
  - `_batched_log`: acumula texto; flush a cada ~800 chars ou na virada de estágio → `ExecutionLog(sequence++)` +
    `execution_ws_manager.notify_log(card_id, "info", chunk)`.
  - `_pause(reason, context)`: `_move(card,"paused")`; grava `workflow_error`/`result` na `Execution` (status `error`
    ou um `paused` textual), `is_active=False`; `notify_complete(status="paused", error=reason)`.
- [ ] Testes (stub `stage_fn` que devolve `StageResult` roteirizado por `stage_key` + contador):
  - caminho feliz: plan→implement→review-limpo → card termina em `validate_ci`; `Execution.status=success`;
    ≥1 `ExecutionLog`.
  - fix-loop: reviewer retorna blocks 1×, depois limpo → card passa por `implement` 2×, termina `validate_ci`.
  - não-converge: reviewer sempre com blocks → após `maxIterations`, card em `paused`.
  - needs_human no implement → card em `paused`, sem chegar em review.
  - pending no plan → card em `paused`, sem implement.
- [ ] Commit: `feat(pipeline): orquestrador de estágios com fix-loop, pause e avanço de coluna`.

### Task A8: endpoints (dispara em background; consulta run + logs)

**Files:** Modify `backend/src/routes/runner.py`. Test: `backend/tests/test_runner_routes.py` (novo).

- [ ] `POST /api/projects/{project_id}/cards/{card_id}/execute`: valida Project+Card; cria `Execution(running)` e
      commita; dispara `asyncio.create_task(run_pipeline(project_id, card_id))`; retorna `{success, executionId}` **na hora**.
      (Não bloquear no pipeline. O `run_pipeline` reabre sua própria sessão.)
- [ ] `GET /api/projects/{project_id}/cards/{card_id}/execution`: devolve o `Execution` ativo (ou último) + seus
      `ExecutionLog` ordenados por `sequence` (pra reload/histórico do painel).
- [ ] Teste (monkeypatch `run_pipeline` p/ no-op): `execute` retorna 200 com `executionId`; `execution` GET devolve o run.
- [ ] Commit: `feat(runner): execute dispara pipeline em background + GET execution p/ o painel`.

### Task A9: revalidação backend

- [ ] `./venv/Scripts/python.exe -m pytest tests/ -v` — as novas passam; baseline (`test_project_manager`,
      `test_test_result_analyzer`) segue com as falhas pré-existentes conhecidas (ignorar).
- [ ] Subir o backend e conferir boot limpo (`Dev workflow seeded`).

---

## Grupo B — Frontend (fino)

### Task B1: client de pipeline + reabilitar Run

**Files:** Create `frontend/src/api/pipeline.ts`. Modify `frontend/src/components/Card.tsx` (o botão hoje `false && …`).

- [ ] `runPipeline(projectId, cardId)` → `POST .../execute`; `getExecution(projectId, cardId)` → run + logs.
- [ ] Reabilitar a ação **Run** no card (só quando há `currentProjectId`); onClick → `runPipeline`; feedback (spinner/toast).
- [ ] `npx tsc --noEmit` limpo (fora os ~7 erros `NodeJS` pré-existentes — conferir via `git stash` que não introduzi novos).
- [ ] Commit: `feat(front): client de pipeline + botão Run no card`.

### Task B2: painel de logs (execution_ws)

**Files:** Create `frontend/src/components/ExecutionLogPanel.tsx`. Modify onde o card abre detalhe/modal.

- [ ] Ao abrir um card em execução: `getExecution` (histórico) + conecta `ws://…/api/execution/ws/{cardId}`; append de
      `type:"log"` e destaque de `type:"execution_complete"` (status success/paused/error). Auto-scroll; fecha o WS ao desmontar.
- [ ] Commit: `feat(front): painel de logs de execução por card (streaming via WS)`.

### Task B3: card avança de coluna ao vivo

**Files:** Modify `frontend/src/App.tsx` (handler do WS de cards).

- [ ] No `card_moved`/`execution_complete`, refetch dos cards do projeto (ou reposiciona pelo payload) — o card sobe de
      coluna sem reload. Se o `CardWS` global não conectar (bug de baseline), usar refetch no `execution_complete` do
      `execution_ws` como fallback.
- [ ] Commit: `feat(front): board reflete avanço de coluna do pipeline ao vivo`.

---

## Grupo C — Verificação end-to-end

### Task C1: smoke real (gasta Max — só `spike-loop-test`)

- [ ] Registrar/abrir o projeto `spike-loop-test`; criar card pequeno (ex.: "adiciona função de subtração + teste").
- [ ] Disparar `execute`; acompanhar o run: card passa plan→implement→review; conferir no repo-alvo a worktree com
      **commit**, `plan.md` em `.sismais/`, e o `validate_ci` como parada. Logs no `execution_logs`.
- [ ] Se o reviewer apontar algo, confirmar 1 volta de fix-loop.

### Task C2: QA visual (Chrome MCP)

- [ ] Run dispara pelo card; painel mostra logs em streaming; card avança de coluna no board; estado final coerente.

### Task C3: docs + memória

- [ ] Atualizar `docs/ARQUITETURA_E_ESTADO.md` (3b-resto ✅, o que o runner já faz) e a memória do projeto.
- [ ] Push (bare `git push` do dir do fork).

---

## Self-review (cobertura vs spec)

- Sequência de colunas → A5/A6/A7. Streaming em lote → A7 (`_batched_log`) + B2. Fix-loop → A7. Pause-or-Decide →
  A4/A7. Avançar coluna → A7 (`_move`). Commit pelo backend → A2/A7. Persistência → `Execution`/`ExecutionLog` (A7/A8).
  `ColumnId` → A1. Background + WS → A7/A8/B2/B3. Cleanup conservador → mantido (helper já existe; auto só em `done`).
- Fora de escopo mantido fora: PR/CI (3c), cortes/consolidação (3d), trilha SDD completa, model-por-etapa.
