# Sismais AI Orquestrador — Fase 3a: Board dirigido por config (colunas + validação de move) — Design

**Data:** 2026-07-03
**Status:** Aprovado (usuário delegou as decisões de design; revisão pós-implementação)
**Relação:** Primeira sub-fase da Fase 3 (runner). Decomposição: **3a** (board config-driven) → 3b (runner no backend) → 3c (PR/CI/ready-to-merge) → 3d (cortes finais + consolidação). Backend 2b-1 já expõe `GET /api/workflows/{id}` e o workflow "dev" (8 colunas). Frontend 2b-2 já tem seletor de projeto + `projectId` nas chamadas.

## Objetivo

O board passa a renderizar as **colunas do workflow config** (`/api/workflows/dev`: `backlog → plan → implement → review → validate_ci → ready_to_merge → done` + `paused`) em vez das 9 colunas hardcoded antigas (`…test…done/completed/archived/cancelado`). O move de card é validado pelas **transições do config** (front e back). Unifica os 3 lugares hardcoded. É fundação para o runner (3b) — **não** implementa execução de agente.

## Decisões (tomadas no lugar do usuário)

1. **Colunas vêm do config.** O board busca o workflow do projeto atual (via `Project.workflowId`, default `dev`) e renderiza `columns` na ordem `order`. Fim do `COLUMNS` hardcoded.
2. **Validação de move pelo config**, front (`isValidTransition(transitions, from, to)`) e back (`card_repository.move` usa as transições do workflow, não o `ALLOWED_TRANSITIONS` hardcoded).
3. **Automação SDLC do browser DESLIGADA nesta fase.** O ladder de triggers em `App.tsx` (`handleDragEnd`) e o `useWorkflowAutomation.runWorkflow` são keyed às colunas antigas (`test`, `completed`…) e serão **substituídos pelo runner no backend (3b)**. Em 3a, mover card = só move (validado pelo config); o botão "Run workflow" e o auto-trigger no drag ficam **inertes/ocultos** com nota apontando pra 3b. (Mudança de comportamento consciente — a execução volta, no backend, na 3b.)
4. **Side-effects de move reconciliados:** remover o `done → migrations` em `.claude/database.db` (morto no modelo banco-único). Manter `diff-capture` em `review`/`done` e `completed_at` em `done` (ambas as colunas seguem existindo). `validate_ci`/`ready_to_merge`/`paused` sem side-effect por ora (runner trata em 3b/3c).
5. **Special-casing de coluna generalizado:** o colapso hardcoded de `archived`/`cancelado`/`completed` (que somem) sai; colunas renderizam uniformemente. Coluna com flag `isPausedState`/`isTerminal` pode ser renderizada mais discreta (opcional). CSS por-id vira estilo default quando não houver classe específica.
6. **Migração de cards existentes:** remapear `column_id` fora do conjunto novo — `test→review`, `completed→done`, `archived→done`, `cancelado→paused` — via migração leve idempotente. (Dado de dev, volume baixo.)
7. **Model picker (AddCardModal):** inalterado nesta fase (o stage `test` fica sem uso; YAGNI mexer agora — o runner em 3b lê os modelos que precisar). Registrado como dívida p/ 3b.

## Arquitetura / componentes

- **Backend:**
  - `card_repository.move(card_id, new_column_id)` → carrega o workflow do projeto do card (helper `get_workflow_transitions(session, project_id)`; default `dev`) e valida com `is_valid_transition`. Remove `ALLOWED_TRANSITIONS` local + o bloco de migrations-on-done.
  - `light_migrations`: novo passo idempotente que remapeia `cards.column_id` legado → novo (só quando o valor não está no conjunto novo).
- **Frontend:**
  - `api/workflows.ts` — `getWorkflow(id)` → `{columns, transitions}`.
  - `App.tsx`/`KanbanPage` — buscar o workflow (do `currentProjectId` → workflow do projeto, ou `dev`), guardar `columns`/`transitions` em estado, passar `columns` ao board; `isValidTransition` usa `transitions`.
  - `Board.tsx`/`Column.tsx` — remover special-casing por id; render uniforme a partir das colunas do config.
  - Desligar o auto-trigger no `handleDragEnd` (mover valida por config + persiste, sem disparar execução) e ocultar/inertizar "Run workflow" (nota → 3b).

## Data flow

Board monta → `getWorkflow(currentProject.workflowId ?? 'dev')` → colunas/transições em estado → render. Drag → `isValidTransition(transitions,…)` → `cardsApi.moveCard` → backend valida pelo config → persiste → broadcast WS.

## Testes

- Backend: `card_repository.move` aceita transição válida do config e rejeita inválida (pytest com um workflow semeado); migração leve remapeia colunas legadas (idempotente).
- Frontend: verificação visual (Chrome MCP) — board mostra as 8 colunas do config; mover card entre colunas válidas funciona; transição inválida é barrada; card legado aparece na coluna remapeada.

## Critérios de aceitação

1. Board renderiza as **8 colunas do config** (não mais as 9 hardcoded).
2. Mover card respeita as transições do config (front + back); inválida é barrada.
3. Cards legados aparecem na coluna remapeada (sem `test`/`completed`/`archived`/`cancelado` órfãos).
4. Sem execução de agente disparada pelo drag (desligado até 3b); app sobe, sem imports quebrados.
5. Testes de backend passam; QA visual confirma o board.

## Fora de escopo (próximas sub-fases)

Runner no backend / execução de agente (3b); PR/CI/ready-to-merge (3c); remover ActiveProject/db_manager, cortar Live/Orchestrator/Gemini, consolidar as duas UIs de projeto (3d).
