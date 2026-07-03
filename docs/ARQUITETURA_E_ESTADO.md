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
- `services/runner_service.py` (worktree + copia `devkit/.claude`) · `services/stage_runner.py` (roda **um estágio**
  do DevKit como `query()` focada: corpo do `.md` do agente vira system prompt, tools do agente = `allowed_tools`) ·
  `services/pipeline_service.py` (**o orquestrador**) · `services/findings.py` (parse de achados/pendências).
- `POST /api/projects/{pid}/cards/{cid}/execute` dispara o pipeline **em background** (retorna `executionId` na hora);
  `GET .../execution` devolve o run + logs (reload do painel).
- **O backend é o orquestrador** (ocupa o papel da skill `sismais-dev-loop`; os `.mjs` de estado não foram migrados de
  propósito). Fluxo por card, **1 worktree reusada**: `plan → implement → review`, cada coluna rodando seu agente de
  estágio; **fix-loop** review→implement (teto `maxIterations=4` → pausa); **Pause-or-Decide** (pendências do plan,
  `needs_human`, não-convergência, exceção → card em `paused`); **avança a coluna** do card (config); o backend **commita**
  na branch (excluindo os dirs injetados `.claude`/`.sismais`); logs em **lote** → `execution_ws` + `execution_logs`.
  Review limpo → avança pra `validate_ci` e **para** (fronteira 3c).
- **Provado (real, spike-loop-test):** card percorreu plan→implement→review com **2 voltas de fix-loop** e parou em
  `validate_ci` (~$2 via Max); painel de logs no board renderiza o histórico. Estado/logs nas tabelas `executions`/`execution_logs`.
- **Ainda NÃO faz:** push/PR/CI/ready-to-merge (**3c**); trilha SDD completa no `plan` (hoje só planner); model-por-etapa;
  auto-cleanup completo de worktree (helper existe; hoje mantém a worktree p/ 3c/inspeção).

### DevKit (a camada de agentes)
- Vive em `devkit/.claude/` (`skills/`, `agents/`, `commands/`), migrado do repo de plugins
  `sismais-ai-plugins-private`. O runner o carrega por-run copiando pra worktree.
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
| 3c | push → `gh pr create --draft` → espera-CI (`ci-triage`) → **para no ready-to-merge** | ⏳ |
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
