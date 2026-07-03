# Sismais AI Orquestrador — Painel de Workflows de Agentes (v1) — Design

**Data:** 2026-06-17
**Repo:** `sismais/ai-orquestrator-agent` (privado) — **fork** de `eduwxyz/orquestrator-agent` ("Zenflow")
**Licença:** MIT (declarada no README do upstream) — **atribuição ao autor original obrigatória** (preservar copyright; adicionar/ajustar o arquivo `LICENSE`).
**Status:** Aprovado para implementação (design)
**Relação com o Sismais AI DevKit:** este projeto é o **cockpit** que dirige o DevKit. O DevKit **sai** do repo de plugins (`sismais-ai-plugins-private`) e passa a viver aqui como camada de agentes.

## Contexto e objetivo

Um **painel Kanban que dirige e acompanha agentes de IA** operando sobre projetos reais. Cada coluna do board é uma etapa executada por uma **skill-agente**; o backend orquestra a sequência (plan → implement → review → validar → PR → CI) numa **git worktree** isolada por card, com **logs ao vivo** no board, parando no **ready-to-merge** para o humano aprovar e fazer o merge.

Nasce como fork do Zenflow (que provou a experiência) e é **reposicionado**: como colunas = agentes e o workflow é **configurável**, o mesmo motor serve **qualquer área da Sismais** (dev, marketing, suporte…). O DevKit é o **primeiro workflow**; outros setores entram como novas configs de workflow + seus agentes.

Substitui o modelo "plugin instalável" do DevKit: ninguém instala nada em `~/.claude`; o **web app é a porta de entrada** e dirige tudo. (O DevKit continua sendo skills/comandos Claude Code — só que carregados localmente pelo orquestrador via Agent SDK, não distribuídos como plugin.)

## Decisões fundamentais

- **Monorepo:** DevKit + web app no mesmo repo (este fork). App-only no v1 (sem marketplace/plugin distribuído).
- **v1 religa direto ao DevKit** (não é passthrough do Zenflow), com verificação por incremento.
- **Backend orquestra, coluna = agente:** a orquestração do loop **migra do `SKILL.md` para o backend**; os **agentes** (planner/implementer/reviewer/…) são reusados via `claude-agent-sdk`.
- **Genérico por arquitetura, dev-first na entrega:** workflow (`colunas + agente-por-coluna + transições`) é **config/dados**, não hardcoded. v1 traz **1 workflow: dev**.
- **Multi-projeto de 1ª classe:** registrar N repos-alvo; **seletor de projeto**; board por projeto; worktree-por-card no repo do projeto.
- **Ingestão:** endpoint `POST` estável cria card no backlog (gancho pronto); apps **não** instrumentados no v1.
- **Para no ready-to-merge; humano faz o merge.** Nunca toca `main`, nunca faz merge.
- **Claude-only no v1** (corta o caminho Gemini do upstream).

## Escopo da v1

### Dentro
1. Monorepo organizado (`backend/`, `frontend/`, `devkit/`, `docs/`), fork limpo.
2. **Projetos** 1ª classe + seletor; board por projeto; worktree-por-card.
3. **Workflow como config** + o **workflow de dev** carregado de config (não hardcoded).
4. **Runner no backend** que sequencia as colunas, roda o **fix-loop** (Review→Implement), validação, PR e espera-CI, e para no ready-to-merge.
5. Agentes do DevKit em `devkit/` (specify/clarify/plan/tasks/implementer/reviewer/ci-triage), carregados pelo SDK.
6. **Logs ao vivo por etapa** (WebSocket + persistência + polling) e **crash-recovery**.
7. Estado **Paused/needs-human** (Pause-or-Decide vira card pausado com motivo).
8. **Endpoint de ingestão** `POST` → card no backlog.
9. Custo/tokens por card. Testes da lógica nova (runner, config de workflow, worktree).

### Fora (futuro)
- Instrumentar apps-alvo pra ingestão automática de erros (v2).
- Editor visual de workflow + boards de outras áreas (marketing etc.) — a arquitetura suporta; a UI/config vem depois.
- `orchestrator_service` autônomo do upstream (auto-decompor Goal, execução paralela) e autonomia total (card nasce e dispara sozinho).
- Qdrant + embeddings (memória de "learnings"); página `/live` + votação; caminho Gemini.
- Auto-merge (nunca; humano sempre faz).

## Arquitetura

### Monorepo
```
ai-orquestrator-agent/
├── backend/     # FastAPI + SQLite — orquestrador: runner de workflow, git/worktree, gh/CI, WebSocket
├── frontend/    # React + @dnd-kit — board: seletor de projeto, colunas, logs ao vivo
├── devkit/      # DevKit: skills/commands/agents (.claude/) + helpers — os "agentes" das etapas
├── docs/        # docs do projeto (inclui agent-sdk-*.md do upstream — referência de integração)
└── docs/superpowers/{specs,plans}/   # nossos specs/planos (este doc + DevKit migrado)
```
O DevKit não é plugin distribuído; o **orquestrador carrega as skills localmente** para o SDK (mecanismo exato — user-scope, dir de skills do SDK, ou copiar pra worktree — a fechar no plano, usando `docs/agent-sdk-skills.md`/`agent-sdk-slash-commands.md`).

### Motor (backend orquestra)
Para cada card, na worktree do projeto-alvo, o backend **sequencia as colunas do workflow**; cada coluna-agente = uma chamada `claude-agent-sdk` na worktree, com logs streamados. O runner roda o **fix-loop** (Review com bloqueios → volta a Implement, com teto), a validação (`validateCommand`), o push, o PR e a **espera-CI** (corrige falha relacionada ao diff), e **para no ready-to-merge**. É a orquestração que estava no `sismais-dev-loop` `SKILL.md`, agora em código no backend.

### Dois eixos de config
- **Workflow** (*o quê*): `{colunas[{key,label,agent|null}], transições}` como dados. v1: **dev**.
- **Projeto** (*onde*): `{repo, rulesFile, validateCommand, baseBranch, workflowId}`.
- **Board = projeto × workflow.** GMS Web e App2 = dois projetos, mesmo workflow de dev, boards separados.

### Ingestão
`POST /api/ingest` (contrato estável) cria card no backlog de um projeto (título/descrição/contexto). Apps não instrumentados no v1 — o gancho fica pronto.

## Workflow de dev (colunas → DevKit)

| Coluna | Agente/ação |
|-|-|
| **Backlog** | card criado (manual ou via `/api/ingest`) |
| **Plan** | pipeline (`specify → clarify → plan → tasks`) → spec + plano + tarefas na worktree |
| **Implement** | `sismais-dev-implementer` |
| **Review** | `sismais-dev-reviewer` (independente); bloqueios → volta a Implement (fix-loop, teto) |
| **Validate/CI** | backend: `validateCommand` → push → abre PR → espera CI (corrige falha relacionada via `ci-triage`) |
| **Ready to merge** | humano aprova e faz o merge (board mostra sugestão de merge) |
| **Done** | pós-merge |

Estado transversal **Paused/needs-human**: o Pause-or-Decide (tarefa ambígua, decisão de produto/arquitetura, ação destrutiva) pausa o card com `{reason, context}`.

## Data model (evolução do Zenflow)

- **Project** `{id, nome, repoPath, remote, rulesFile, validateCommand, baseBranch, workflowId}`
- **Workflow** `{id, nome, colunas:[{key,label,agent|null}], transicoes}`
- **Card** `{id, projectId, titulo, descricao, coluna, branch, worktreePath, prUrl, status, pause:{reason,context}|null, diffStats, custo}`
- **Execution** `{id, cardId, coluna, logs:[], tokens, custo, status, isActive}` (uma por rodada de etapa; a ativa marcada)

## Do Zenflow: manter / cortar / consertar

- **Manter (adaptar):** board `@dnd-kit`; colunas+transições → generalizadas pra config; **worktree-por-card** (`backend/src/git_workspace.py`, o mais reusável); stream SDK → WS + persistência + polling; crash-recovery; custo/tokens; Project → multi-projeto.
- **Cortar no v1:** Qdrant + `sentence-transformers`; página `/live` + votação; caminho **Gemini**; arquivos-lixo do autor (`amanha.txt`, `todo.txt`, `todos2.txt`, `hello.py`, `prompt.txt`, `image.png`).
- **Consertar:** orquestração sai do browser (`frontend/.../useWorkflowAutomation.ts`) → **runner no backend**; **parar no ready-to-merge** em vez do stub de merge; deduplicar `backend/src/agent.py` (~2600 linhas) ao religar pro DevKit.
- **Adiar:** `services/orchestrator_service.py` (autônomo).

## Migração do DevKit (honesto)

- **Reusar:** os **agentes** — skills `specify/clarify/plan/tasks` + `implementer/reviewer/ci-triage` — vão para `devkit/`.
- **Substituir (não migram como estão):** a **orquestração e o estado** (`sismais-dev-loop` `SKILL.md`, `run-state.mjs`, `loop-state.mjs`) são substituídos pelo backend (Card/Execution no banco).
- **Docs:** a SPEC/planos do DevKit vão para `docs/superpowers/{specs,plans}/` deste repo.
- **Repo de plugins:** remover/deprecar o DevKit de lá (decidir no plano). `hello-internal` e futuros plugins de setor permanecem.

## Stack

Mantém a do fork (menos retrabalho): **FastAPI + SQLAlchemy 2 async + SQLite** (backend), **React 18 + TS + Vite + @dnd-kit** (frontend), **`claude-agent-sdk` (Python)** para rodar os agentes. Sem migração de stack. Onboarding Python/React do time = item do plano.

## Riscos e mitigações

- **Adotar 31k LOC de terceiro** — mitigar cortando cedo (Qdrant/Live/Gemini/lixo) e religando por incremento com verificação; não big-bang.
- **Carregar skills do DevKit no SDK** (mecanismo não trivial) — usar os docs `agent-sdk-*.md` do próprio fork; resolver no início do plano com um spike.
- **Portar a orquestração do loop pro backend** — a lógica (fix-loop, guardrails, CI, Pause-or-Decide) está bem descrita no `sismais-dev-loop` design; portar 1:1.
- **gh/CI a partir do backend** (auth, chamadas na worktree) — validar cedo; degradação clara se `gh` ausente.
- **Licença/atribuição** — adicionar `LICENSE` MIT com atribuição ao autor original antes de publicar.
- **Validação plena é e2e real** (SDK + gh + CI) — unit-testar a lógica nova (runner, config, worktree); o fluxo completo valida no smoke.

## Critérios de aceitação (v1)

1. Registrar ≥2 projetos (GMS Web + outro), trocar pelo seletor, board por projeto.
2. Criar um card no GMS Web e rodar → backend faz Plan→Implement→Review(fix-loop)→Validate→PR→CI e **para em ready-to-merge**, com **logs ao vivo por etapa**, em **worktree** isolada; nunca toca `main`, nunca faz merge.
3. Tarefa ambígua → card em **paused_for_human** com motivo.
4. Sobrevive a fechar/reabrir a aba (crash-recovery reata a execução em andamento).
5. `POST /api/ingest` cria card no backlog (sem app instrumentado).
6. O workflow de dev é carregado de **config** (trocar colunas/agentes não exige mexer no motor).
7. Sem Qdrant/Live/Gemini; runner no backend; testes da lógica nova passam; `LICENSE` com atribuição.

## Questões em aberto (a resolver no plano)

- Mecanismo exato de carregar as skills do DevKit no SDK (user-scope × skill dir × copiar pra worktree) — spike inicial usando `docs/agent-sdk-skills.md`.
- Como o runner sequencia + faz o fix-loop no backend (portar a lógica do loop pra Python) e onde entram guardrails/Pause-or-Decide.
- Estratégia de dedup do `agent.py` ao religar.
- Schema exato das tabelas (Workflow config, transições) e migração do schema do fork.
- Como o backend chama `gh`/CI na worktree (auth, espera de checks).
- Remover vs deprecar o DevKit no repo de plugins.
- Onboarding do stack (Python/FastAPI/React) pro time.
