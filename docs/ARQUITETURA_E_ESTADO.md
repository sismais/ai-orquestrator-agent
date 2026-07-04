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
- **LEGADO desligado:** o `database_manager.py` multi-arquivo (`.claude/database.db` por projeto) e o
  `ActiveProject` (projeto "ativo global") **ainda existem no código mas fora do caminho de sessão**
  (`get_session()` devolve o engine único). Remoção definitiva = Fase 3d.
- Migrações: **sem Alembic**. `create_all` + `light_migrations.py` (ALTER idempotente + `remap_legacy_columns`).

### Multi-projeto (project-scoped)
- **Registro de projetos:** tabela `Project` + API `/api/registry/projects` (CRUD). Cada projeto tem
  `path` (repo local), `rulesFile` (default `AGENTS.md`), `validateCommand`, `baseBranch`, `workflowId`.
- Chamadas de card carregam `projectId` (`GET /api/cards?projectId=`, `POST` com `projectId`).
- **Frontend:** seletor de projeto no header do board (`ProjectSelectorRegistry`) — troca sem reload.
  ⚠️ Ainda há os controles **antigos** `ProjectSwitcher`/`ProjectLoader` no header (ligados ao
  `ActiveProject`/execução legada) — consolidar na Fase 3d.

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
- **Ainda NÃO faz:** trilha SDD completa no `plan` (hoje só planner); model-por-etapa; auto-cleanup de worktree.

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
- `POST .../say` (base pronta) injeta mensagem na sessão ao vivo — **falar sem parar** é o incremento 2 (falta o laço
  multi-turno + a caixa no painel). Spec: `specs/2026-07-03-panel-chat-ao-vivo-stop-design.md`.
- **Provado (real, spike-loop-test):** Stop durante o `plan` interrompeu a sessão de verdade → pausou → respondi a
  correção → retomou plan→implement→review→`validate_ci`. Confirma também que a troca `query()`→client não regrediu o pipeline.

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
- **Orchestrator autônomo** (`orchestrator_service.py`): desligado no boot (`ORCHESTRATOR_ENABLED=false`).
- **Página `/live` + votação**; **caminho Gemini** (`agent.py` dual-provider, `gemini_*`): entrelaçados,
  adiados. Board só usa Claude.
- **`agent.py` (~2600 linhas)**: caminho legado de execução (`/plan`,`/implement` etc.). Será
  substituído/deduplicado pelo runner; hoje o board **não** dispara mais o auto-run no drag
  (`AUTO_RUN_ON_DRAG = false` em `App.tsx`).

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
| 3d | Remover `ActiveProject`/`database_manager`/ativo-global; cortar Live/Orchestrator/Gemini; consolidar os 2 controles de projeto | ⏳ |

## Design/planos versionados (superpowers) — começar por aqui ao retomar

- Specs: `docs/superpowers/specs/` — design geral do painel + Fase 2 + Fase 3a.
- Planos: `docs/superpowers/plans/` — Fase 1, 2a, 2b-1, 2b-2 (frontend).
- Notas: `docs/superpowers/notes/` — **`2026-06-17-fork-code-map.md`** (mapa do código p/ as próximas fases,
  com pontos de acoplamento) e `2026-06-17-spike-skill-loading.md` (como o SDK carrega o DevKit em worktree).

## Arquivos-chave (atualizados)

- `backend/src/main.py` — app, routers, lifespan (create_tables → light_migrations → remap → seed workflow).
- `backend/src/database.py` — engine único via `DATABASE_URL`; `get_session()`.
- `backend/src/services/{runner_service,stage_runner,pipeline_service,findings}.py` — **o runner + pipeline** (3b).
- `backend/src/models/execution.py` — `Execution`/`ExecutionLog` (estado do run + logs; reusados pelo pipeline).
- `backend/src/routes/{cards,projects_registry,workflows,runner}.py` — APIs project-scoped.
- `backend/src/repositories/card_repository.py` — `move()` valida por config.
- `backend/src/services/{workflow_seed,workflow_rules,light_migrations}.py` — config + migração de colunas.
- `backend/src/git_workspace.py` — worktree por card (reusar).
- `frontend/src/App.tsx` — estado do board (colunas do config, `currentProjectId`, `AUTO_RUN_ON_DRAG`).
- `frontend/src/api/{cards,projectsRegistry,workflows}.ts` — clients.
- `frontend/src/components/{Board,Column,Card}` — render das colunas do config.

## Bugs de baseline conhecidos (do fork, não regressão)
- `GET /api/metrics/productivity/current` → 500 (`Card has no attribute 'status'`) em `metrics_repository.py`.
- WebSocket `CardWS` (`/api/cards/ws`) falha ao conectar no load. Tratar quando mexer no data model/WS.
