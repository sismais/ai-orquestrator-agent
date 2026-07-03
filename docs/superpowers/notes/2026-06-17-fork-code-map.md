# Mapa do código do fork — para as Fases 2–4

**Data:** 2026-06-17 · Entrega da Fase 1 (Task 6). Consolida a exploração feita ao subir e
enxugar o fork. Caminhos e símbolos verificados no código.

## Máquina de estados / colunas — **hardcoded em 3 lugares** (Fase 2 unifica)

- `frontend/src/types/index.ts:145` `COLUMNS`, `:158` `ALLOWED_TRANSITIONS`, `:170` `isValidTransition`.
- `backend/src/repositories/card_repository.py:15` `ALLOWED_TRANSITIONS` (usado em `:141`).
- `backend/src/schemas/card.py:29` `ColumnId = Literal["backlog","plan","implement","test","review","done","completed","archived","cancelado"]`.
- **Fase 2 (workflow como config):** unificar os três numa fonte única + mapa `coluna→agente/comando`.
  Hoje as colunas do fork (`plan/implement/test/review`) não batem 1:1 com o workflow de dev do
  design (`Plan/Implement/Review/Validate-CI/Ready-to-merge`) — reconciliar.

## Runner (hoje no **browser**) — Fase 3 move pro backend

- `frontend/src/hooks/useWorkflowAutomation.ts` — sequencia as etapas e faz crash-recovery no
  cliente (`recoveringWorkflowsRef`, `recoveryProcessedRef` ~`:41-44`). Acoplado aos nomes de etapa.
- **Fase 3:** portar a orquestração (fix-loop, guardrails, CI, Pause-or-Decide — descritos no
  `sismais-dev-loop` `SKILL.md`) para um runner no backend, dirigindo o SDK.

## Invocação do SDK / prompts — `backend/src/agent.py` (~2600 linhas)

- 5 pontos com `ClaudeAgentOptions(...)` + `query(...)`: linhas **1422, 1712, 2035, 2375, 2576**.
  Padrão comprovado: `cwd=<worktree>`, `setting_sources=["user","project"]`,
  `allowed_tools=["Skill","Read","Write","Edit","Bash","Glob","Grep","TodoWrite"]`,
  `permission_mode="acceptEdits"`, `prompt="/plan ..."` (slash command).
- Funções: `execute_plan` / `execute_implement` / `execute_test_implementation` / `execute_review`
  / `execute_expert_triage`. Cada uma tem **branch Gemini + branch Claude** (dual-provider).
- **Fase 3 religa ao DevKit:** trocar os comandos do fork (`/plan`,`/implement`,`/test`,`/review`)
  pelos nossos (`/sismais-dev*` + agentes), usar o mecanismo do spike (worktree-copy de
  `devkit/.claude` + `setting_sources=["project"]`, ver `2026-06-17-spike-skill-loading.md`), e
  **deduplicar** o dual-provider (só Claude).

## Worktree — `backend/src/git_workspace.py` (reusar)

- `create_worktree:109`, `cleanup_worktree:176`, `list_active_worktrees:215`,
  `cleanup_orphan_worktrees:237`. Endpoints em `main.py` (`/api/cards/{id}/workspace`, `/api/branches`,
  `/api/cleanup-orphan-worktrees`). **Ponto de enxerto** da cópia `devkit/.claude` por-run (Fase 3).

## Custo / tokens (já config-driven — reusar)

- `backend/src/config/pricing.py`, `backend/src/services/cost_calculator.py`, `ResultMessage.usage`.

## Multi-projeto (hoje global/most-recent) — Fase 2 torna 1ª classe

- `backend/src/models/project.py` `ActiveProject` (o board usa "o projeto ativo mais recente").
- `backend/src/database_manager.py` `db_manager` (DB por projeto; `database.py:60,86` resolve sessão).
- **Fase 2:** seletor de projeto + board por projeto (registrar N repos; hoje é implícito).

## PR / merge — **GAP (vaporware)**, Fase 3/4 constrói

- `frontend/src/hooks/useWorkflowAutomation.ts:445` `handleCompletedReview` é **placeholder**
  (`:446` `console.warn(... "Automatic merge not implemented yet")`), chamado por `App.tsx:598`.
- `frontend/src/components/Card/Card.tsx:348` botão **"Create PR"** — sem backend real.
- **Fase 3/4:** implementar push → `gh pr create --draft` → espera-CI → parar em **ready-to-merge**
  (nunca fazer merge). É o núcleo do valor; hoje não existe.

## Fix-card (reusar mais tarde)

- `backend/src/services/test_result_analyzer.py` `TestResultAnalyzer` (usado em `agent.py:1870`).
- `backend/src/models/card.py:35` `parent_card_id`, `:40` `is_fix_card`. Base pro fix-loop no backend.

## Cortes ADIADOS para a Fase 3 (decisão do usuário — entrelaçados com o núcleo reescrito)

Removidos na Fase 1 só os cortes seguros (lixo, `docker-compose.yml`, `sentence-transformers`).
Os subsistemas abaixo ficam **inertes** até a Fase 3 (orchestrator desligado via
`ORCHESTRATOR_ENABLED=false`; Gemini não ofertado), pois acoplam ao código que a Fase 3 reescreve:

- **Live/votação:** `backend/src/routes/live.py`, `services/{presence,voting,live_broadcast}_service.py`,
  `schemas/live.py`, `models/live.py`, `frontend/src/{pages/LivePage,components/Live,components/LiveModeControl,hooks/useLiveWebSocket,types/live}`.
  **Acoplamento crítico:** `agent.py:525` usa `get_live_broadcast_service()` (streaming) — desacoplar
  ao reescrever o runner.
- **Orchestrator autônomo:** `routes/orchestrator.py`, `services/orchestrator_service.py` (~1200 l.),
  `memory_service.py`, `qdrant_service.py`, `embedding_service.py`, `config/qdrant.py`,
  `models/orchestrator.py`. **Acoplamento:** `chat_service.py:194/244` (`_submit_goal_to_orchestrator`).
  Remover `qdrant-client` do `requirements.txt` **junto** (hoje ainda é import de topo via `routes/orchestrator.py`).
- **Gemini (Claude-only):** branches em `agent.py` (funções plan/implement/test/review),
  `gemini_agent.py`, `services/gemini_service.py`, `agent_chat.py`, prompts `GEMINI_*_PROMPT`,
  `google-generativeai` no `requirements.txt`, `GEMINI_API_KEY` no `.env.example`, e os modelos
  Gemini no seletor do frontend.

## Bugs de baseline observados (pré-existentes do fork — não corrigidos na Fase 1)

- **`GET /api/metrics/productivity/current` → 500:** `AttributeError: type object 'Card' has no
  attribute 'status'` em `backend/src/repositories/metrics_repository.py:352`. (O "erro de CORS" no
  console do board é só efeito colateral do 500.) Os demais endpoints de métrica respondem 200.
- **WebSocket `ws://localhost:3001/api/cards/ws`** falha ao conectar no load do board (`CardWS`).
- **`requirements.txt` faltava `email-validator`** (corrigido na Fase 1 → `pydantic[email]`).

Tratar quando a Fase 2 mexer no data model / Fase 3 no runner e WS.
