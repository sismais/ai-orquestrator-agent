# Sismais AI Orquestrador — Interação humana no card (pausa → comentário → retoma) — Design

**Data:** 2026-07-03
**Status:** Aprovado (usuário aprovou a mecânica: pausa vira comentário no card + resposta destrava retomada automática)
**Relação:** Fecha o **Pause-or-Decide** do pipeline (Fase 3b-resto). Fica antes da 3c. Base para o passo futuro
(chat ao vivo com o agente, com Stop no meio — fora deste escopo).

## Objetivo

Quando o pipeline **pausa** um card (pendência do plan, `needs_human` no implement, não-convergência no review), a
**pergunta do agente aparece como comentário no card**. O humano **responde no card**; a resposta fica registrada
(outro comentário) e **retoma o pipeline automaticamente** a partir da etapa pausada, com a resposta no contexto do
agente. Nada de merge/PR (isso é 3c).

## Decisões (aprovadas pelo usuário)

1. **Thread de comentários = `activity_logs`** (já existe: `ActivityType.COMMENTED` + `description`). A pausa cria um
   comentário do **agente** (a pergunta); a resposta cria um comentário do **humano**. Autor via `user_id` sentinela
   (`"agent"` | `"human"`). O card ganha um mini-thread (reusa `GET /api/activities/card/{id}`).
2. **Retoma automático.** Ao responder, o pipeline retoma sozinho da etapa pausada (sem botão separado).
3. **Etapa de retomada** (regra simples, sem campo novo): a partir do `workflow_stage` da `Execution` pausada —
   `plan`→`plan`, `implement`→`implement`, `review`(não-convergência)→`implement` (a resposta guia a correção; zera o
   contador de iterações). A resposta humana entra no prompt da etapa como contexto.
4. **Guardas:** só responde se o card estiver **pausado** (Execution ativa com status `paused`). Resposta vazia é
   rejeitada. Reusa o `run_pipeline` em background (não bloqueia o request).

## Arquitetura / componentes

**Backend**
- `models/activity_log.py` — sem mudança de schema; convenção de autor em `user_id` (`agent`/`human`).
- `repositories/activity_repository.py` — helper `add_comment(card_id, author, text)` (grava `COMMENTED`).
- `services/pipeline_service.py`:
  - No `finish_pause(reason, context, *, question)`: além de pausar, grava **comentário do agente** com a pergunta
    (a `question` = texto amigável derivado do motivo/contexto).
  - `run_pipeline(..., resume_stage=None, human_answer=None)`: se `resume_stage`, começa nele (em vez de `_first_stage`),
    injeta `human_answer` no `extra` da primeira etapa, e (se veio de não-convergência) zera `iteration`.
  - `build_stage_prompt` (stage_runner) aceita `extra["human_answer"]` → prepende "Resposta do humano à pausa: …".
- `routes/runner.py` — `POST /api/projects/{pid}/cards/{cid}/answer` (body `{message}`): valida card pausado; grava
  comentário do humano; calcula `resume_stage` a partir do `workflow_stage` da última Execution; dispara
  `run_pipeline(..., resume_stage, human_answer=message)` em background; retorna `{success, executionId}`.
- `GET .../cards/{cid}/execution` (já existe) — o front usa `workflowError`/status `paused` p/ saber que há pergunta.

**Frontend**
- `api/pipeline.ts` — `answerPipeline(projectId, cardId, message)` (POST `/answer`); `getCardActivities(cardId)`.
- `components/PipelineControls` — quando o card está em `paused`: mostra a **pergunta** (do último comentário do agente
  / `workflowError`) + **caixa de resposta**; enviar → `answerPipeline` → o card sai de `paused` (WS `card_moved`).
- Thread de comentários (pergunta/resposta) exibido de forma compacta no card ou no modal de logs (reusa activities).

## Data flow

Pausa → `finish_pause` grava comentário do agente (pergunta) + card em `paused`. Front detecta `paused` → mostra
pergunta + caixa. Humano responde → `POST /answer` → grava comentário do humano + `run_pipeline(resume_stage,
human_answer)` em background → move card de `paused` → etapa de retomada (roda com a resposta no prompt) → segue o
laço normal. Board atualiza via `card_moved`; logs via `execution_ws`.

## Testes

- **Backend unit:** `run_pipeline` com `resume_stage="implement"` + `human_answer` (stub `stage_fn`) → começa no
  implement, injeta a resposta, segue até `validate_ci`. `finish_pause` grava comentário do agente. `POST /answer`
  rejeita card não-pausado e aceita card pausado (monkeypatch `run_pipeline`). Regra de `resume_stage` (review→implement).
- **Smoke real (spike-loop-test):** um card cuja tarefa force pausa (decisão ambígua sem base → `pendingQuestions`, ou
  gatilho de `needs_human`); responder no card; confirmar retomada e conclusão. **Só spike-loop-test.**
- **QA visual:** card pausado mostra pergunta + caixa; ao responder, sai de `paused` e avança.

## Critérios de aceitação

1. Card pausado mostra a **pergunta do agente** como comentário e uma **caixa de resposta**.
2. Responder grava o comentário do humano e **retoma o pipeline automaticamente** da etapa pausada, com a resposta no
   contexto do agente.
3. Só é possível responder card pausado; resposta vazia é barrada.
4. Board/ą painel refletem: card sai de `paused` e avança; thread pergunta→resposta fica registrado.
5. Testes de backend passam; smoke real verde; QA visual confirma.

## Fora de escopo

Chat ao vivo bidirecional durante a execução + **Stop** no meio (próximo passo, exige sessão persistente do agente —
`ClaudeSDKClient` em vez do `query()` por etapa); múltiplas perguntas simultâneas; edição/threading avançado de comentários.
