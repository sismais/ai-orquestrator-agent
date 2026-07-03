# Sismais AI Orquestrador — Fase 2: Multi-projeto de 1ª classe + Workflow como config — Design

**Data:** 2026-07-02
**Repo:** `sismais/ai-orquestrador-agent` (privado)
**Status:** Aprovado para implementação (design)
**Relação:** Fase 2 de 4 do painel (ver `2026-06-17-ai-orquestrador-panel-design.md`). Fundação (Fase 1) concluída; runner no backend é a Fase 3.

## Contexto e objetivo

Tornar o painel **multi-projeto de 1ª classe** e o **workflow uma configuração de dados** (não hardcoded), deixando o backend **parallel-ready** — pronto pra operar N projetos simultâneos. É fundação de dados: **não** implementa o runner (Fase 3). Ao fim, o board renderiza colunas a partir do config, suporta vários projetos com dados isolados, e o schema já nasce no formato que migra pra Supabase por troca de connection-string.

## Fronteira de escopo

- **Dentro:** modelo de dados (banco único tenant-shaped), backend project-scoped (sem "ativo global"), Workflow em tabela semeada, board dirigido por config, seletor de projeto, provider+model por coluna (Claude), migração do modelo multi-arquivo atual, testes da lógica nova.
- **Fora (Fase 3+):** o runner que sequencia colunas / fix-loop / CI / PR; dispatch real de providers não-Claude; editor visual de workflow; boards de outras áreas; ida efetiva ao Supabase.

## Decisões fundamentais (fechadas no brainstorm)

1. **Banco único, SQLite agora, tenant-shaped.** Uma base só, com `project_id` nas tabelas tenant-scoped (cards, execuções). Sem arquivo-por-projeto.
2. **DB vive no repo do orquestrador**, caminho por `.env` (`DATABASE_URL`); default `backend/orchestrator.db` (gitignored). **Nunca** dentro dos projetos-alvo. Remove `STORE_DB_IN_PROJECT`/`AUTO_MIGRATE_LEGACY_DB` e o `database_manager` multi-arquivo.
3. **Supabase-ready por swap.** SQLAlchemy async fala SQLite e Postgres com o mesmo código; ir pro Supabase depois = trocar `DATABASE_URL` + rodar migrations. Nada de lock-in.
4. **Backend project-scoped (parallel-ready).** Some o "projeto ativo global": toda requisição carrega `project_id`; queries filtram por ele. Isolamento de dados = `project_id`; isolamento de execução/arquivos = **worktree por card** (já existe).
5. **Workflow como config em tabela**, semeada no boot com o workflow **dev** (7 colunas). Editável via API depois.
6. **Colunas do workflow dev:** `Backlog → Plan → Implement → Review → Validate/CI → Ready-to-merge → Done` + estado transversal **Paused**. (Muda o board atual — mudança de UX consciente.)
7. **Provider-agnostic.** Cada coluna carrega `provider` (default `claude`) + `model`. UI escolhe o modelo Claude por etapa (opus/sonnet/haiku). Dispatch multi-vendor é interface da Fase 3 (gancho pronto, nada construído).
8. **Project registry** próprio (tabela `Project`), separado do "projeto em foco".

## Modelo de dados (banco único)

Tabelas **globais** (sem `project_id`): `users`, `projects`, `workflows`.
Tabelas **tenant-scoped** (com `project_id` FK): `cards`, `executions`, `execution_logs`, métricas.

- **Project** — `{id, name, path, remote?, rulesFile="AGENTS.md", validateCommand, baseBranch="main", workflowId→Workflow, favorite, createdAt, lastOpenedAt}`. Fonte da verdade do catálogo de projetos.
- **Workflow** — `{id, name, columns:[Column], transitions:{fromKey:[toKey...]}, createdAt}`.
  - **Column** — `{key, label, order, agentKey|null, provider="claude", model|null, isPausedState=false, isTerminal=false}`. `agentKey` liga a coluna a um agente/comando do DevKit (ou `null` = manual/ação de backend).
- **Card** — passa a ter `project_id` FK; `column_id` referencia `Column.key` do workflow do projeto. (Migração das colunas antigas → novas.)
- **Execution / ExecutionLog / métricas** — ganham `project_id` FK.

> **Onde ficam os agentes:** o `agentKey` é lógico; o mapeamento `agentKey → comando/skill do DevKit` (`/sismais-dev-*`) é resolvido pelo runner na Fase 3, usando `devkit/.claude`. A Fase 2 só armazena e valida o config.

### Workflow dev semeado (v1)

| key | label | agentKey | provider/model | observação |
|-|-|-|-|-|
| `backlog` | Backlog | — | — | manual / `POST /api/ingest` |
| `plan` | Plan | `plan` | claude / (default) | pipeline specify→clarify→plan→tasks |
| `implement` | Implement | `implement` | claude | sismais-dev-implementer |
| `review` | Review | `review` | claude | sismais-dev-reviewer; bloqueios → volta a `implement` |
| `validate_ci` | Validate/CI | `validate-ci`\* | — | ação de backend (validateCommand + gh); \*não-agente |
| `ready_to_merge` | Ready to merge | — | — | humano aprova/mergeia |
| `done` | Done | — | — | terminal (`isTerminal=true`) |
| `paused` | Paused | — | — | transversal (`isPausedState=true`) |

Transições semeadas incluem o fix-loop (`review→implement`) e o caminho feliz. **Execução delas = Fase 3**; na Fase 2 as transições só **validam** movimentação manual de card.

## Arquitetura — mudanças-chave

### Persistência (single engine)
- `database.py`: um único `async_engine` a partir de `DATABASE_URL`. Remover `database_manager.py` (pool multi-arquivo), `current_project_id`, `initialize_project_database`, `.project_data`, `STORE_DB_IN_PROJECT`.
- Sessão resolvida por request (um `async_session_maker` só). Isolamento por `project_id` na query, não por engine.

### Project-scoping (parallel-ready)
- Endpoints tenant-scoped viram `/api/projects/{projectId}/...` (cards, execuções, métricas, worktree, logs, chat). Remover `get_active_project()`/`ActiveProject` como "ativo global".
- Camada de repositório recebe `project_id` e filtra sempre. Guard: request sem `project_id` válido → 400.
- Worktree (`git_workspace.py`) já é por-card no path do projeto (via `Project.path`); manter, só passar a resolver o path pelo `projectId` da rota (não pelo ativo global).

### Frontend
- **ProjectSelector** no topo: lista `projects` (ordenado por `favorite`/`lastOpenedAt`), ação "adicionar projeto" (aponta path local → cria `Project`), troca de projeto = navega pro board daquele projeto (ex.: rota `/:projectId`). `projectId` em foco no estado/URL; todas as chamadas o incluem.
- **Board dirigido por config:** colunas e transições vêm do `Workflow` do projeto (via API), não de `types/index.ts`. Unifica as 3 fontes hardcoded (`frontend/src/types/index.ts`, `backend/.../card_repository.py`, `backend/.../schemas/card.py`) → derivadas do config.
- **Model picker por coluna** (Settings do workflow): escolhe modelo Claude por etapa.

## Migração

- **Schema:** migration que (a) cria `projects`, `workflows`; (b) adiciona `project_id` a `cards`/`executions`/`execution_logs`/métricas; (c) semeia o workflow dev.
- **Dados existentes:** consolidar eventuais DBs por-projeto (`<proj>/.claude/database.db`, `.project_data/*`) num só, carimbando `project_id`; migrar linhas de `active_project` → `projects`. Colunas antigas de card → novas (`test→review`, `completed→done`, `archived/cancelado→` mantidas como legacy/terminal). Best-effort e documentado (ferramenta nova, volume provável baixo).
- **`.gitignore`:** garantir `backend/orchestrator.db*` (inclui `-wal`/`-shm`) ignorados.

## Testes (lógica nova)

- Seed/carga do Workflow (colunas/transições corretas); validação de transição **derivada do config**.
- CRUD do `Project` registry; defaults (`rulesFile`, `baseBranch`).
- **Isolamento por `project_id`:** dois projetos → cards não vazam entre si (query filtra); operações concorrentes não interferem.
- Defaults de `provider`/`model` por coluna.
- Resolução de sessão single-engine (sem `current_project_id`).

## Critérios de aceitação (Fase 2)

1. Registrar ≥2 projetos; ambos no seletor; trocar mostra **boards independentes** (dados isolados por `project_id`).
2. Board renderiza as 7 colunas **do config**; mover card respeita as transições do config.
3. Backend **project-scoped**, sem ativo global; dois projetos operáveis simultaneamente (criar card em cada, sem interferência).
4. Banco **único** vivendo no repo/`.env` (não dentro dos projetos); schema tenant-shaped; troca pra Postgres/Supabase = só `DATABASE_URL` + migrations.
5. Cada coluna carrega `provider`+`model`; UI escolhe modelo Claude por etapa; schema pronto pra outros providers.
6. Testes novos passam; app sobe e board carrega. (Execução do fluxo = Fase 3.)

## Riscos e mitigações

- **Refactor amplo (project-scoping) toca muitos endpoints + frontend** — maior esforço da fase. Mitigar: fazer por camadas (schema+migração → repositórios com `project_id` → rotas → frontend), com o app subindo a cada camada.
- **Remover `database_manager` sem quebrar** — mapear todos os usos de `db_manager`/`get_current_session` antes; substituir por sessão única.
- **Mudança de colunas quebra a automação browser atual** — aceito: essa automação é substituída na Fase 3; documentar que o board fica data-driven sem executor até lá.
- **Escrita concorrente no SQLite** (logs) — não impede paralelo; ressalva só em carga alta. Mitigar na Fase 3 com **lote de logs** no runner (buffer ~250ms/insert em lote). Registrado pro plano da Fase 3.

## Questões em aberto (para o plano)

- Nomes/estrutura exata das migrations (SQLAlchemy/Alembic? o fork usa `create_all` — decidir estratégia de migração no plano).
- Formato do mapa `agentKey → comando DevKit` (tabela? constante? resolvido no runner) — definir na fronteira com a Fase 3.
- Rota/URL do board por projeto (`/:projectId` vs querystring) e persistência do "último projeto em foco" (client-side).
