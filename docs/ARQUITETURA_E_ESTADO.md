# Sismais AI Orquestrador — Arquitetura & Estado

> Doc canônico do estado atual. O `CLAUDE.md` é só o bootstrap; o detalhe vive aqui.
> **Cuidado:** este é um **fork do Zenflow** em reforma. Muito código legado ainda existe mas está
> **desligado/adiado** — não confie no comportamento antigo; confie neste doc + no que está ativo.

## O que é

Painel Kanban que **dirige agentes de IA** (o **Sismais AI DevKit**) operando sobre projetos reais.
Cada coluna é uma etapa; o **backend orquestra** a execução numa **git worktree isolada por card**,
com logs, parando no **ready-to-merge** para o humano aprovar/mergear. Nunca faz merge sozinho.

## Arquitetura atual (o que está ATIVO)

- **Backend:** FastAPI + SQLAlchemy 2 async + **SQLite único** · porta **3001**.
- **Frontend:** React 18 + Vite + @dnd-kit · porta **5173**.
- **Execução de agente:** `claude-agent-sdk` (Python) roda o Claude Code por baixo. **Auth = login do
  Claude Code CLI (assinatura Max)** — sem `ANTHROPIC_API_KEY` (a chave é opcional, só p/ forçar a API).

### Banco (mudou vs Zenflow)
- **Banco único** `backend/orchestrator.db` (via `DATABASE_URL` no `.env`), gitignored, **tenant-shaped**:
  tabelas globais (`users`, `projects`, `workflows`) + tenant-scoped por `project_id` (`cards`, `executions`…).
- **Supabase-ready:** SQLAlchemy async fala SQLite e Postgres — migrar = trocar `DATABASE_URL` + migrations.
- **LEGADO REMOVIDO (2026-07-07):** o `database_manager.py` multi-arquivo (`.claude/database.db` por projeto), o
  `ActiveProject`, o `project_manager.py` e o `project_history` **foram apagados** — `get_session()` devolve o engine único.
- Migrações: **sem Alembic**. `create_all` + `light_migrations.py` (ALTER idempotente + `remap_legacy_columns`).

### Multi-projeto (project-scoped)
- **Registro de projetos:** tabela `Project` + API `/api/registry/projects` (CRUD). Cada projeto tem
  `path` (repo local), `rulesFile` (default `AGENTS.md`), `validateCommand`, `baseBranch`, `workflowId`.
- Chamadas de card carregam `projectId` (`GET /api/cards?projectId=`, `POST` com `projectId`).
- **Frontend:** seletor de projeto **app-level** no `TopNav` (`ProjectSelectorRegistry`, via `WorkspaceLayout`) —
  escopa **todos os módulos** (board + chat), troca sem reload. Os controles antigos (`ProjectSwitcher`/`ProjectLoader`)
  foram removidos.

### Workflow como config
- Tabela `Workflow` (semeada no boot com o workflow **`dev`**): `columns[]` + `transitions{}`.
  Colunas dev: `backlog → plan → implement → review → validate_ci → ready_to_merge → done` + `paused`.
- **Board renderiza as colunas do config** (`GET /api/workflows/dev`), não hardcoded.
- **Move validado pelo config** (front `isValidMove`, back `card_repository.move` via `is_valid_transition`).

### Runner / Pipeline (Fase 3b — completa; 3b-core + 3b-resto provados)
- `services/runner_service.py` (worktree pristina, sem injetar DevKit) · `services/stage_runner.py` (roda **um estágio**
  do DevKit como `query()` focada: corpo do `.md` do agente vira system prompt, tools do agente = `allowed_tools`) ·
  `services/pipeline_service.py` (**o orquestrador**) · `services/findings.py` (parse de achados/pendências).
- `POST /api/projects/{pid}/cards/{cid}/execute` dispara o pipeline **em background** (retorna `executionId` na hora);
  `GET .../execution` devolve o run + logs (reload do painel).
- **O backend é o orquestrador** (ocupa o papel da skill `sismais-dev-loop`; os `.mjs` de estado não foram migrados de
  propósito). Fluxo por card, **1 worktree reusada**: `plan → implement → review`, cada coluna rodando seu agente de
  estágio; **fix-loop** review→implement (teto `maxIterations=4` → pausa); **Pause-or-Decide** (pendências do plan,
  `needs_human`, não-convergência, exceção → card em `paused`); **avança a coluna** do card (config); o backend **commita**
  na branch (worktree pristina → commita só as mudanças reais do projeto, incl. o `.claude` dele); o `plan` devolve o
  plano como **texto** (passado ao implement, sem arquivo no repo); logs em **lote** → `execution_ws` + `execution_logs`.
  Review limpo → avança pra `validate_ci` e **para** (fronteira 3c).
- **Provado (real, spike-loop-test):** card percorreu plan→implement→review com **2 voltas de fix-loop** e parou em
  `validate_ci` (~$2 via Max); painel de logs no board renderiza o histórico. Estado/logs nas tabelas `executions`/`execution_logs`.
- **Modelo-por-etapa LIGADO (2026-07-07):** `stage_runner.run_stage(model=)` passa o modelo escolhido (`card.model_*`
  por coluna, via `pipeline_service.stage_model_for_column`) ao SDK, resolvido pelo mapa único `config/model_ids.py`.
- **Ainda NÃO faz:** trilha SDD completa no `plan` (hoje só planner); auto-cleanup de worktree.

### validate_ci → PR draft → espera CI → ready_to_merge (Fase 3c — provada)
- Coluna `validate_ci` ganhou handler próprio (git/gh, não um agente): `services/validate_ci_stage.run_validate_ci` +
  `services/pr_service.py` (push/PR/CI via `gh`). O dispatcher do pipeline roteia `plan|implement|review`→agente,
  `validate_ci`→`run_validate_ci`.
- Fluxo: **valida local** (se `project.validateCommand`, com fix-loop) → **push** da branch → **`gh pr create --draft`**
  (idempotente; URL na `Execution.result`, exposta em `GET .../execution` como `prUrl`) → **espera CI** (poll de
  `gh pr view --json statusCheckRollup`; sem checks = verde) → verde → card em **`ready_to_merge`** e run `success`.
  CI vermelha → **ci-triage** (`sismais-dev-ci-triage`): `related`→implementer corrige→push→re-espera; `unrelated`→segue;
  teto→pausa. **Nunca faz merge nem promove o PR a ready** — para no ready_to_merge (decisão do humano).
- Front: link **🔗 Ver PR** no card em ready_to_merge.
- **Provado (real):** `pr_service` fez push + abriu **PR draft #2** no spike-loop-test (draft/OPEN, idempotente),
  check_status leu `none` (sem CI → verde). Orquestração coberta por 43 testes unitários. Spec:
  `specs/2026-07-03-panel-fase3c-pr-ci-design.md`. (PR de teste fechado/branch apagada após o smoke.)

### Interação humana no card (Pause-or-Decide fechado)
- Ao **pausar**, a pergunta do agente vira **comentário no card** (`activity_logs`, `COMMENTED`, autor em `user_id`
  = `agent`/`human`). `POST /api/projects/{pid}/cards/{cid}/answer` grava o comentário do humano e **retoma o pipeline
  automaticamente** (`run_pipeline(resume_stage, human_answer)`), reusando a worktree e injetando a resposta no prompt
  da etapa. Etapa de retomada: `plan`→`plan`, `implement`→`implement`, `review`(não-convergência)→`implement`.
- **Provado (real, spike-loop-test):** pausou no `plan` (pergunta) → resposta → replanejou → `implement` → pausou de
  novo (`needs_human`) → resposta → implementou → `review` → `validate_ci`. Front: `PipelineControls` mostra a pergunta
  + caixa "Responder e retomar" no card `paused`. Spec: `specs/2026-07-03-panel-interacao-humana-no-card-design.md`.
### Chat ao vivo — Stop (interromper para corrigir)
- Cada etapa agora roda numa **sessão `ClaudeSDKClient`** (streaming interrompível), não mais `query()` de tiro único.
  `services/session_registry.py` guarda a sessão ativa por card; `stage_runner.run_stage` registra/desregistra.
- `POST /api/projects/{pid}/cards/{cid}/stop` → `client.interrupt()` → o estágio encerra e o pipeline **pausa** o card
  ("interrompido pelo usuário") → o humano corrige na aba Interação → **retoma** (máquina de pausa/retomada existente).
  Front: botão **⏹ Stop** só em card de etapa ativa (plan/implement/review) + rodando.
- **`/say` (falar sem parar) — TENTADO E REVERTIDO (2026-07-05):** o laço multi-turno **pendura a etapa** quando o SDK
  absorve a mensagem injetada no turno atual (o `receive_response()` seguinte bloqueia pra sempre). Modelo do SDK é
  turn-based. Revertido pro single-turn seguro; a intervenção robusta é o **Stop→corrige→retoma**. `/say` correto
  exigiria `receive_response` com timeout no 1º chunk — trabalho futuro. Spec: `specs/2026-07-03-panel-chat-ao-vivo-stop-design.md`.
- **Provado (real, spike-loop-test):** Stop durante o `plan` interrompeu a sessão de verdade → pausou → respondi a
  correção → retomou plan→implement→review→`validate_ci`. Confirma também que a troca `query()`→client não regrediu o pipeline.

### Projeto = escopo do app (chat project-scoped + seletor app-level + modelos) — feito 2026-07-07/08
- **Seletor de projeto app-level:** subiu do board pro `TopNav` (via `WorkspaceLayout`); escopa board **e** chat.
- **Chat project-scoped + persistido em DB:** tabelas `chat_session`/`chat_message` (com `project_id`) + `repositories/chat_repository.py`.
  O cwd do agente do chat vem do `Project.path` selecionado (`agent_chat.stream_response(cwd=)`, sem `ActiveProject`); o
  contexto do Kanban no system_prompt é filtrado por projeto. Rotas exigem `projectId` (`POST /api/chat/sessions`,
  `GET /api/chat/sessions?projectId=`).
- **Gestão de conversas (UI + rota):** `/chat` = **lista** de conversas do projeto (título = 1ª mensagem, data, excluir);
  `/chat/:sessionId` = conversa aberta (reload reabre; reload em `/chat` fica na lista, sem abrir nenhuma). `useChat(projectId,
  activeSessionId)` é dirigido pela rota (react-router `useNavigate`/`useLocation`; a nav de módulos segue por estado `currentView`).
- **Modelos atualizados:** `opus-4.8`/`sonnet-5`/`haiku-4.5` + `fable-5` (beta, **disabled** nos pickers), Gemini removido,
  **1M de contexto** em opus/sonnet. Mapa único alias→id do SDK em `config/model_ids.py` (usado por chat **E** pipeline).
- **Convenção WS (ping/pong):** os 3 WebSockets (chat, `/api/cards/ws`, `/api/execution/ws/:cardId`) respondem `{type:"pong"}`
  ao `{type:"ping"}` do `useWebSocketBase` (heartbeat 30s) — senão o cliente estoura o pongTimeout e reconecta em loop.
- **CLAUDE.md do projeto-alvo carrega no chat** (verificado empírico): `setting_sources=["user","project"]` + cwd = raiz do
  projeto carregam o `CLAUDE.md` e resolvem os `@imports` (ex.: `@AGENTS.md`). O pipeline usa o preset `claude_code` +
  `setting_sources=["project"]` (carrega igual), mas roda em worktree → só enxerga arquivos **commitados**.
- Specs/planos: `docs/sismais-devkit/specs/2026-07-07-projeto-escopo-do-app-*.md` + `plans/2026-07-07-projeto-escopo-app-feature.md`
  e `plans/2026-07-07-remocao-subsistema-legado.md`.

### Onda "Agora" da revisão estratégica (A1–A6) — feito 2026-07-09
- **Robustez (A1):** try/except de topo em `run_pipeline` (erro interno → pausa, com traceback logado e
  rollback no último recurso) + done-callback nas tasks de background; `startup_recovery.recover_orphan_executions`
  no boot pausa Executions RUNNING órfãs de restart (guard: nunca derruba o boot).
- **Falha-fechada (A2):** review sem JSON parseável re-pede 1x e pausa (nunca aprova —
  `parse_review_findings_strict`; a tolerante delega para ela); estágio com turno vazio pausa; snippet
  anti-parada-prematura apendado ao system prompt de todo estágio (`stage_runner.AUTONOMY_SNIPPET`, válvula de
  escalação ancorada ao contrato do estágio); `build_stage_options` é o ponto único de options (plug futuro de
  perfis por modelo — onda N1).
- **Pausa visível (A3):** coluna `paused` é a **primeira** do board (seed do workflow virou **upsert** —
  config-as-code); toast global de pausa (escopado ao projeto atual) + contador "aguardando você" no TopNav
  (WS `card_moved`; `CardResponse` agora expõe `projectId`).
- **Telemetria (A5):** `Execution` ganha tokens/`model_used` (do `ResultMessage.usage`) + `fix_iterations`;
  expostos em `GET .../execution`; LogsModal mostra custo real do run; `costStats` do card prefere o
  `execution_cost` real do SDK ao derivado por tokens.
- **Chat (A6):** contexto Kanban dirigido pelo workflow config (inclui paused/validate_ci/ready_to_merge, com
  `[id8]` do card), atividades escopadas por projeto, bloco "Projeto atual" no system prompt (projectId
  obrigatório na criação de cards, worktrees em `.worktrees/card-<id8>/`, curls de histórico e resolução de id).
- **Contexto (A4):** `Card.requested_by` + `Project.objective` (light migrations); header do prompt dos
  estágios com projeto/objetivo/solicitante/`rules_file` do projeto (hardcode "AGENTS.md" removido do prompt);
  contrato dos `.md` do DevKit (planner/implementer/reviewer) alinhado ao que o backend envia; campo
  "Objetivo" no modal de novo projeto.
- Spec de origem: `specs/2026-07-09-revisao-estrategica-plataforma.md` · Plano: `plans/2026-07-09-onda-agora-melhorias.md`.

### Onda N1 — perfis por modelo + recusa com fallback — feito 2026-07-10
- `config/model_ids.py` virou **registry de perfis** (`ModelProfile`: model_id, fallback_alias,
  prompt_append); `resolve_model_id`/`ALIAS_TO_MODEL_ID` preservados como compat.
- `stage_runner.run_stage` virou laço de política sobre `_run_single_attempt`: fim de turno
  **classificado** (`_classify_result` sobre `ResultMessage.stop_reason/is_error/api_error_status`
  do SDK 0.2.110) — **recusa → 1 retry no modelo de fallback do perfil** (ex.: fable-5 → opus-4.8),
  erro transiente (HTTP 429/5xx) → 1 retry no mesmo modelo, interrupção nunca re-tenta; custo/usage
  somados entre tentativas; `StageResult.used_model` = modelo real (telemetria registra pós-fallback).
- ci-triage roda com modelo explícito (`fix_model`). **fable-5 habilitado nos pickers.**
- Plano: `plans/2026-07-10-onda-n1-perfis-modelo.md`.

### Onda N2 — router de complexidade — feito 2026-07-10
- Estágio de **triagem** no início de todo run novo partindo do backlog: agente
  `devkit/.claude/agents/sismais-dev-router.md` (haiku-4.5, com fallback de recusa da N1) classifica
  **leve** (pula o `plan`, começa no `implement` — transição nova `backlog → implement` no seed) ou
  **padrao** (fluxo completo). Advisory: erro/não-parse → `padrao` (nunca bloqueia); Stop pausa.
- Override humano: retomadas e cards posicionados manualmente fora do backlog NÃO re-triam.
- Trilha + justificativa nos logs do run; `Execution.track` persistida e exposta em `GET .../execution`.
- Plano: `plans/2026-07-10-onda-n2-router-complexidade.md`.

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
- Pausa e retomada resolvem a coluna pelo config (fix do review).
- Plano: `plans/2026-07-10-onda-n4-dispatcher-config.md`.

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

### Onda N5 — send_to_user + auditoria de tool calls — feito 2026-07-10
- **Auditoria total:** as tool calls do agente (Read/Edit/Bash/…) viram logs tipados `tool`
  (`stage_runner._format_tool_use`) — antes só o texto era registrado; erros de tool também.
  `_LogSink.__call__` aceita `log_type` e serializa writes com `asyncio.Lock`.
- **Progresso:** tool in-process **`send_to_user`** (SDK MCP, padrão Anthropic 2) plugada por run
  via `build_stage_options(progress_cb=)`; emite logs `progress` ao card sem encerrar o turno;
  `PROGRESS_SNIPPET` instrui o uso no system prompt (definir a tool não basta).
- Front: LogsModal e PipelineControls renderizam `tool`/`progress` distintamente.
- Plano: `plans/2026-07-10-onda-n5-send-to-user-auditoria.md`.

### Onda N6 — ciclo fechado no board + limpeza da UI legada — feito 2026-07-10
- **Merge detectado:** `pr_service.get_pr_state` (`gh pr view --json state`) + endpoint
  `POST .../cards/{cid}/check-merge` move o card `ready_to_merge → done` quando o PR foi mergeado
  no GitHub (idempotente; **nunca faz merge** — só detecta o do humano). PipelineControls faz poll
  leve (20s) enquanto o card está em ready_to_merge + botão "Verificar merge"; o card fecha via WS.
- **UI legada removida:** o Card perdeu os badges/mensagens de execução legados ("Executing /plan…",
  barra "Planning…"), o botão "Create PR" placeholder, o "View Logs" legado e o banner de merge morto;
  `useWorkflowAutomation` e `useAgentExecution` (hooks mortos), o bloco `AUTO_RUN_ON_DRAG`, o poll de
  merge morto e os endpoints `execute-*` inexistentes foram apagados. `PipelineControls` é a fonte
  única de execução/PR/logs do card. (Dívida do fork registrada no ARQUITETURA resolvida.)
- Plano: `plans/2026-07-10-onda-n6-ciclo-fechado-limpeza.md`.

### DevKit (a camada de agentes)
- Vive em `devkit/.claude/` (`skills/`, `agents/`, `commands/`), migrado do repo de plugins
  `sismais-ai-plugins-private`.
- **Não é injetado na worktree.** O runner **não copia** o DevKit pro repo do projeto: o papel de cada estágio vem do
  `system_prompt` (`stage_runner` lê o `.md` do agente de `devkit/.claude/agents`), e as skills que o agente usa são as
  **do próprio projeto** (do checkout na worktree). Assim o `.claude` do projeto fica intacto e é commitado normalmente;
  o DevKit nunca polui a branch. (Antes copiava — mudou em 2026-07-03; ver `notes/2026-07-03-spike-devkit-plugin-loading.md`.)
- **Injetar skills-padrão Sismais nos agentes (futuro):** via `plugins=[{type:local,path}]` (provado no spike), com
  `skills` filtrado só pro DevKit. Hoje YAGNI — o backend orquestra, então não precisamos.
- Os scripts de estado `.mjs` **não** foram migrados (o backend é o dono do estado). Ver `devkit/README.md`.

## O que está CORTADO/ADIADO (não usar; remoção final na Fase 3d)
- **Qdrant + embeddings** (memória vetorial): serviços ainda no disco, sem uso; `docker-compose` removido.
- **REMOVIDO na 3d-resto (2026-07-05, ~8.600 linhas):** `agent.py` (execução legada `/plan`,`/implement` + Gemini
  dual-provider), orchestrator autônomo (`orchestrator_service`, `orchestrator_logger`, `orchestrator_repository`,
  `memory_service`, `routes/orchestrator`, `models/orchestrator`, `schemas/orchestrator`), página **/live** + votação
  (`live_broadcast_service`, `voting_service`, `routes/live`, `models/live`, `schemas/live`), `agent_persistence.py`,
  e os endpoints `/api/execute-*` + expert-triage no `main.py`. **Chat preservado** (usa `agent_chat.py`, desacoplado
  do orchestrator). Board só usa Claude; boot OK; testes só com as falhas de baseline.

> **3d-final — FEITO (2026-07-07):** o subsistema legado de "projeto ativo" foi **removido por completo** — `ActiveProject`,
> `database_manager`, `project_manager`, `project_history`, `routes/projects.py` e o `ExpertsModal` órfão (não montado).
> Worktree/git (`main.py`) e o `expert-triage` migraram pro `Project` do registry (resolvem por `project_id`); FK do
> `metrics` repontado pra `projects.id`; o Chat deixou de usar `ActiveProject` (cwd = `Project.path` selecionado). Detalhe
> na seção "Projeto = escopo do app" acima. **Dívida frontend — RESOLVIDA na onda N6:** `useAgentExecution`/`useWorkflowAutomation`
> e a UI de execução legada do `Card` foram removidos; `PipelineControls` é a fonte única.

## Estado das fases

| Fase | O quê | Status |
|-|-|-|
| 1 | Fundação/de-risk (sobe enxuto, DevKit migrado, spike de skill-loading, rebrand+LICENSE) | ✅ |
| 2a | Banco único tenant-shaped, tabelas Project/Workflow (seed dev), migração leve | ✅ |
| 2b-1 | Backend project-scoped: API registry, workflow, cards por project_id | ✅ |
| 2b-2 | Frontend: seletor de projeto + projectId nas chamadas + troca sem reload | ✅ |
| 3a | Board dirigido por config (colunas + move por config); auto-run desligado | ✅ |
| **3b-core** | **Runner executa agente real em worktree do projeto** | ✅ **provado** |
| **3b-resto** | Sequenciar colunas, streaming de logs pro board (WS+lote), fix-loop, Pause-or-Decide, avançar coluna, commit pelo backend | ✅ **provado** |
| **3c** | push → `gh pr create --draft` → espera-CI (`ci-triage`) → **para no ready-to-merge** | ✅ **provado** |
| 3d | Consolidar os 2 controles de projeto no header | ✅ **feito** |
| 3d-resto | Cortar agent.py/orchestrator/live/gemini (mantendo o Chat) — ~8.600 linhas | ✅ **feito** |
| 3d-final | Remover `ActiveProject`/`database_manager`/`project_manager` (worktree/git + experts → registry; FK metrics → `projects.id`; chat cwd → `Project.path`) | ✅ **feito (2026-07-07)** |
| Feature | Projeto = escopo do app: seletor app-level, chat project-scoped + persistido + gestão de conversas/rotas, modelos + modelo-por-etapa, ping/pong dos WS | ✅ **feito + smoke browser** |

## Design/planos versionados (superpowers) — começar por aqui ao retomar

- Specs: `docs/sismais-devkit/specs/` — design por fase (painel, Fase 2/3a/3b/3c, interação humana, chat-stop, projeto=escopo do app).
- Planos: `docs/sismais-devkit/plans/` — por fase (1 → 3d) + a feature "projeto = escopo do app" (feature + remoção do legado).
- Notas: `docs/sismais-devkit/notes/` — **`2026-06-17-fork-code-map.md`** (mapa do código p/ as próximas fases,
  com pontos de acoplamento) e `2026-06-17-spike-skill-loading.md` (como o SDK carrega o DevKit em worktree).

## Arquivos-chave (atualizados)

- `backend/src/main.py` — app, routers, lifespan (create_tables → light_migrations → remap → seed workflow).
- `backend/src/database.py` — engine único via `DATABASE_URL`; `get_session()`.
- `backend/src/services/{runner_service,stage_runner,pipeline_service,findings}.py` — **o runner + pipeline** (3b).
- `backend/src/models/execution.py` — `Execution`/`ExecutionLog` (estado do run + logs; reusados pelo pipeline).
- `backend/src/routes/{cards,projects_registry,workflows,runner,chat,experts}.py` — APIs project-scoped.
- `backend/src/{models/chat.py, repositories/chat_repository.py, services/chat_service.py, agent_chat.py}` — chat project-scoped + persistido.
- `backend/src/config/model_ids.py` — mapa único alias→id do SDK (chat **e** pipeline); `config/pricing.py` — preços.
- `backend/src/repositories/card_repository.py` — `move()` valida por config.
- `backend/src/services/{workflow_seed,workflow_rules,light_migrations}.py` — config + migração de colunas.
- `backend/src/git_workspace.py` — worktree por card (reusar).
- `frontend/src/App.tsx` — estado do board + roteamento do chat (`/chat`, `/chat/:sessionId`), `currentProjectId`.
- `frontend/src/{layouts/WorkspaceLayout, components/Navigation/TopNav}` — seletor de projeto app-level.
- `frontend/src/{hooks/useChat.ts, pages/ChatPage.tsx, api/chat.ts}` — chat project-scoped + gestão de conversas.
- `frontend/src/hooks/useWebSocketBase.ts` — WS com heartbeat ping/pong (os handlers respondem pong).
- `frontend/src/api/{cards,projectsRegistry,workflows}.ts` — clients.
- `frontend/src/components/{Board,Column,Card}` — render das colunas do config.

## Bugs de baseline conhecidos (do fork, não regressão)
- `GET /api/metrics/productivity/current` → 500 (`Card has no attribute 'status'`) em `metrics_repository.py`.
- 3 testes pré-existentes vermelhos em `tests/test_test_result_analyzer.py` (formatação/encoding) — sem relação com runner/chat.
- ~~WebSocket `CardWS` reconectava em loop~~ → **CORRIGIDO (2026-07-08):** os 3 WS (chat/cards/execução) respondem pong ao heartbeat ping.
