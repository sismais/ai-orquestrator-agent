# Sismais AI Orquestrador — Fase 3b-resto: Pipeline orquestrada pelo backend — Design

**Data:** 2026-07-03
**Status:** Aprovado (usuário delegou as decisões de design; execução autônoma)
**Relação:** Continua a Fase 3b. O **3b-core** já provou o runner executando um agente real numa worktree isolada
(`services/runner_service.py` + `POST /api/projects/{pid}/cards/{cid}/execute`). Esta sub-fase transforma aquele
tiro único num **pipeline sequenciado pelo backend**, com fix-loop, pause, avanço de coluna e streaming pro board.
Fica **antes** da 3c (push→PR→CI) e da 3d (cortes/consolidação).

## Objetivo

O backend passa a **orquestrar o card pelas colunas do workflow** (`plan → implement → review`), executando o
**agente de estágio do DevKit** correspondente a cada coluna, numa **única worktree reusada** ao longo do card.
Ao terminar `review` limpo, **avança e para** na fronteira da 3c (`validate_ci`, sem handler ainda). O board recebe
os **logs ao vivo** e vê o card **avançar de coluna**. Erros/ambiguidades **pausam** o card (Pause-or-Decide) em vez
de inventar. Nada de merge, nada de PR (isso é 3c).

## Tese arquitetural (a decisão central)

**O backend é o orquestrador.** Ele ocupa o papel que a skill `sismais-dev-loop` teria — cujos scripts de estado
`.mjs` **não foram migrados de propósito** (o backend é o dono do estado). Portanto o runner **não** invoca a skill
orquestradora (ela chamaria `${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs`, ausente na worktree, e delegaria via
Task). Em vez disso, para cada coluna com estágio, o runner invoca **um agente de estágio do DevKit** como uma
`query()` focada:

- **system prompt** = corpo do `.md` do agente (`devkit/.claude/agents/sismais-dev-<stage>.md`, sem o frontmatter).
- **allowed_tools** = as tools declaradas no frontmatter daquele agente.
- **cwd** = a worktree do card; `setting_sources=["project"]` (skills do DevKit disponíveis); `permission_mode="acceptEdits"`.

O **estado do run** (iterações, achados, custo, status, motivo de pausa) e os **logs** vivem nas tabelas
**já existentes** `executions` / `execution_logs` (`models/execution.py`). Nada de tabela nova.

## Decisões (tomadas no lugar do usuário)

1. **Registro de estágios (coluna → handler).** Mapa data-driven a partir do `agentKey` da coluna do config:
   | coluna (`agentKey`) | agente DevKit | tools | contrato de saída |
   |-|-|-|-|
   | `plan` | `sismais-dev-planner` | Read, Glob, Grep | escreve `plan.md` na worktree; texto-resumo; pode emitir `{"pendingQuestions":[...]}` → **pausa** |
   | `implement` | `sismais-dev-implementer` | Read, Glob, Grep, Edit, Write, Bash | edita código+testes; `status: done` \| `needs_human` → **pausa** |
   | `review` | `sismais-dev-reviewer` | Read, Glob, Grep, Bash | JSON `{blocks[], fixNow[], suggestions[]}` |
   Colunas **sem handler** (`backlog`, `validate_ci`, `ready_to_merge`, `done`, `paused`) fazem o pipeline **parar** ao
   alcançá-las. `validate_ci` é o handoff natural pra 3c (quando ganhar handler, o pipeline segue sem mudar o orquestrador).

2. **Uma worktree por card, reusada entre estágios.** O plan/implement/review operam no **mesmo** diretório (o código e o
   `plan.md` precisam persistir entre etapas). `worktree_path`/`branch_name` gravados no card (campos já existem).

3. **O backend faz o git; o agente não.** O implementer é instruído a **não** commitar (assim já é o `.md`). Após um
   `implement`/fix bem-sucedido, o **orquestrador commita** na branch da worktree (`git add -A && git commit`), para o
   reviewer ver diff real e a 3c ter o que dar push.

4. **Fix-loop `review → implement`.** Se o reviewer retornar `blocks`+`fixNow` > 0 e as iterações < `maxIterations`
   (default **4**): move o card de volta pra `implement`, despacha o implementer **só com aqueles achados**, commita, e
   **re-revisa** (incrementa a iteração). Ao atingir o teto sem convergir → **pausa** ("não convergiu"). `suggestions`
   nunca bloqueiam.

5. **Pause-or-Decide.** O card vai pra coluna `paused` (e o run marca o motivo/contexto) quando: planner devolve
   `pendingQuestions`; implementer devolve `needs_human`; fix-loop não converge no teto; ou qualquer estágio estoura
   exceção. Pausar **não** apaga a worktree nem os logs (histórico preservado).

6. **Execução em background + streaming.** Um run leva minutos. O endpoint **não bloqueia** o request: cria a linha
   `Execution` (status `running`), dispara o pipeline via `asyncio.create_task` e **retorna já** com o `executionId`.
   O pipeline **abre sua própria sessão de DB** (a do request fecha ao responder) — recebe só `project_id`/`card_id`.
   Logs em **lote** (flush a cada ~800 chars ou na virada de estágio): cada lote vira `ExecutionLog` (sequence++) e é
   transmitido por `execution_ws_manager.notify_log(card_id, ...)`. Viradas de coluna também disparam
   `card_ws_manager.broadcast_card_moved` pro board reposicionar o card ao vivo. No fim: `notify_complete`.

7. **Cleanup de worktree conservador.** Por padrão **mantém** a worktree (o código é necessário pra 3c/inspeção).
   Helper de cleanup disponível (`GitWorkspaceManager.cleanup_worktree`, já existe) + endpoint explícito. Auto-cleanup
   só quando o card chega em `done` (fora do auto-run da 3b, já que `done` vem depois da 3c). Nada de apagar em sucesso.

8. **`ColumnId` vira `str`.** O `Literal` em `schemas/card.py` está preso às colunas antigas (sem `validate_ci`/
   `ready_to_merge`/`paused`) e **barraria** mover pra `paused`. Como o board é config-driven, a validação de coluna é
   do config (`is_valid_transition`), não do schema. Troca por `str` (correção pontual, escopo desta fase).

9. **Modelo por etapa: fora de escopo agora.** As colunas do config têm `model` (hoje `None` = default do CLI). O
   runner usa o default. Ligar `model` por etapa fica pra depois (YAGNI; dívida registrada).

## Arquitetura / componentes

**Backend**
- `services/stage_runner.py` (novo) — `load_stage_agent(stage_key) -> (system_prompt, allowed_tools)` (lê o `.md` do
  agente, separa frontmatter); `run_stage(stage_key, worktree, prompt, on_log) -> StageResult` (roda a `query()`,
  coleta texto/custo). `StageResult{ text, cost_usd, raw }`.
- `services/findings.py` (novo) — `parse_review_findings(text) -> {blocks,fixNow,suggestions}` robusto a cercas de
  código/prosa; `parse_pending_questions(text)`; `detect_needs_human(text)`.
- `services/pipeline_service.py` (novo) — o orquestrador: `run_pipeline(project_id, card_id)`. Sessão própria,
  worktree via `runner_service.prepare_worktree` (reuso), laço de estágios a partir do config
  (`next_active_column`), fix-loop, pause, persistência em `Execution`/`ExecutionLog`, streaming WS, avanço de coluna
  via `CardRepository.move`.
- `git_workspace.py` — 2 helpers novos: `commit_all(worktree_path, message)` e `diff_against_base(worktree_path, base)`.
- `services/workflow_seed.py` / config — helper `next_active_column(columns, transitions, current)` (a sucessora do
  caminho-feliz; a que não é `paused`).
- `routes/runner.py` — `POST .../execute` passa a **disparar o pipeline em background** e retornar `executionId`;
  `GET .../cards/{card_id}/execution` devolve o run ativo + logs (pra reload/histórico).
- `schemas/card.py` — `ColumnId = str`.

**Frontend**
- `api/pipeline.ts` (ou estender `cards.ts`) — `runPipeline(projectId, cardId)`; `getExecution(projectId, cardId)`.
- `components/Card.tsx` — reabilitar a ação **Run** (hoje `false && …`) → chama `runPipeline`.
- `components/ExecutionLogPanel.tsx` (novo) — conecta em `/api/execution/ws/{cardId}`, mostra logs + eventos de
  estágio/pause/complete. Aberto ao clicar no card em execução.
- `App.tsx` — ao receber `card_moved`/`execution_complete` no WS, refetch/re-posiciona o card (o card avança ao vivo).

## Data flow

`POST execute` → cria `Execution(running)` → `asyncio.create_task(run_pipeline(pid,cid))` → responde `{executionId}`.
`run_pipeline`: worktree (reuso) → para cada coluna-com-handler em ordem: `move(card, coluna)` +
`broadcast_card_moved` + `notify_log(stage_start)` → `run_stage(...)` (streaming em lote → `ExecutionLog` +
`notify_log`) → aplica desfecho (commit / fix-loop / pause / avança). Fim → `notify_complete`. Front: Run dispara;
`ExecutionLogPanel` assina o WS; board reposiciona no `card_moved`.

## Testes

- **Backend unit (sem SDK real):**
  - `parse_review_findings` — extrai JSON de saída com prosa/cercas; conta blocks/fixNow/suggestions.
  - `load_stage_agent` — separa frontmatter, mapeia tools corretas por estágio.
  - `next_active_column` — devolve a sucessora do caminho-feliz; ignora `paused`; `None` em terminal.
  - `run_pipeline` com `run_stage` **stub** — sequência plan→implement→review; fix-loop quando o stub do reviewer
    retorna blocks; pausa no teto; pausa em needs_human/pendingQuestions; avança e para em `validate_ci`. Verifica as
    transições de coluna e as linhas `Execution`/`ExecutionLog`.
  - `move` aceita `paused`/`validate_ci` após `ColumnId=str`.
- **Smoke real (gasta Max, só em `maiconsaraiva/spike-loop-test`):** um card pequeno dirigido plan→implement→review;
  verificar avanço de coluna, worktree com commit, e logs transmitidos. **Nenhum outro repo.**
- **QA visual (Chrome MCP):** Run dispara; painel de logs mostra streaming; card avança de coluna no board.

## Critérios de aceitação

1. `POST .../execute` retorna `executionId` **na hora** e o pipeline roda em background.
2. Um card percorre `plan → implement → review` de forma automática, cada coluna rodando seu agente de estágio.
3. Reviewer com `blocks`/`fixNow` > 0 dispara **fix-loop** (volta a `implement`, corrige, re-revisa), com teto que
   **pausa** ao não convergir.
4. `pendingQuestions`/`needs_human`/exceção **pausam** o card em `paused` com motivo registrado (sem apagar worktree).
5. Review limpo **avança** o card pra `validate_ci` e **para** (fronteira 3c).
6. Logs transmitidos ao board por WS (em lote) e persistidos em `execution_logs`; card avança de coluna ao vivo.
7. Testes de backend passam; smoke real em `spike-loop-test` verde; QA visual confirma painel + avanço.

## Fora de escopo (próximas sub-fases)

Trilha SDD completa no `plan` (specifier→clarifier→tasker — hoje só planner); push/PR/CI/ready-to-merge (**3c**);
remover `ActiveProject`/`database_manager`, cortar Live/Orchestrator/Gemini, consolidar as 2 UIs de projeto (**3d**);
model-por-etapa; auto-cleanup completo de worktree.
