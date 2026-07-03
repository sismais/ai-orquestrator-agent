# Sismais AI Orquestrador — Chat ao vivo com o agente + Stop no meio — Design

**Data:** 2026-07-03
**Status:** Aprovado (usuário pediu como próximo passo; execução autônoma)
**Relação:** Evolui a interação humana (pausa→comentário→retoma) para **interação em tempo real** durante a execução de
uma etapa. Usa `ClaudeSDKClient` (sessão streaming interrompível) no lugar do `query()` de tiro único.

## Objetivo

Enquanto uma etapa roda (o agente está trabalhando), o usuário pode **interromper (Stop)** para corrigir o rumo, e —
no incremento seguinte — **falar com o agente ao vivo** (injetar uma mensagem sem parar). Sem perder nada da pipeline
em etapas (colunas, fix-loop, pausa/retomada) já provada.

## Capacidade do SDK (verificada no código instalado)

`claude_agent_sdk.ClaudeSDKClient` (streaming mode): `connect()`, `query(msg)` (manda mensagem no meio),
`receive_messages()`/`receive_response()` (stream), **`interrupt()` (o Stop)**, `set_model()`, `disconnect()`.
Confirma sessão bidirecional interrompível por card.

## Decisões

1. **Sessão por etapa, registrada.** A execução de estágio passa a usar `ClaudeSDKClient` (não `query()`). Um
   registry em memória `active_sessions[card_id] = client` deixa o cliente alcançável pela camada HTTP/WS (para Stop /
   mensagem ao vivo). Como a pipeline é **sequencial por card**, há no máximo 1 sessão ativa por card. Limpa no fim
   do estágio (`finally`: `pop` + `disconnect`).
2. **Stop = interrupt → pausa (reusa a interação).** `POST .../stop` marca `interrupt_flags[card_id]` e chama
   `client.interrupt()`. O estágio corrente encerra; o runner detecta a flag e **pausa o card** (Pause-or-Decide) com
   motivo "interrompido pelo usuário para correção". O usuário então **corrige na aba Interação** e o pipeline
   **retoma** (máquina de pausa/retomada já existente) — a correção entra no prompt da etapa retomada. Zero mecanismo novo de retomada.
3. **Falar ao vivo (incremento 2).** `POST .../say` com `{message}` → `active_sessions[card_id].query(message)`:
   injeta a mensagem na sessão corrente **sem parar**; o agente incorpora e segue na mesma etapa. A mensagem também
   vira comentário `human` no thread. (Requer laço multi-turno com `receive_messages`; fica após o Stop funcionar.)
4. **Equivalência comportamental.** O estágio client-based produz o mesmo streaming de `TextBlock` e o mesmo custo/result
   do `query()` atual — o pipeline (sequência, fix-loop, pausa, avanço, commit) fica **idêntico**; só ganha Stop/say.
5. **Coexistência com a pausa por decisão.** Stop (humano) e pausa por `pendingQuestions`/`needs_human` (agente)
   convergem no mesmo estado `paused` + thread de comentários. A retomada é a mesma.

## Arquitetura / componentes

**Backend**
- `services/stage_runner.py` — novo `run_stage` baseado em `ClaudeSDKClient`:
  - abre cliente, registra em `active_sessions[card_id]`, `await client.query(prompt)`, itera `receive_response()`
    coletando `TextBlock` (→ on_log) e `ResultMessage` (custo). `finally`: desregistra + `disconnect()`.
  - retorna `StageResult` com um flag `interrupted` (lido de `interrupt_flags`).
  - `session_registry.py` (novo): `active_sessions`, `interrupt_flags`, helpers `register/unregister/interrupt(card_id)/say(card_id,msg)/is_active(card_id)`.
- `services/pipeline_service.py` — passa `card_id` ao `run_stage`; se `res.interrupted`, `finish_pause("interrompido pelo
  usuário", question="Você interrompeu. O que devo ajustar?")`.
- `routes/runner.py` — `POST .../stop` (interrupt), `POST .../say` (incremento 2), `GET .../execution` já informa
  `isActive` (running) p/ o front habilitar o Stop.

**Frontend**
- `api/pipeline.ts` — `stopPipeline(projectId, cardId)` (POST `/stop`); `sayToPipeline(...)` (incremento 2).
- `PipelineControls` / painel de logs — enquanto `running`, botão **⏹ Stop** (chama `stopPipeline`). Ao parar, o card
  pausa e a interação assume (aba Interação). (Incremento 2: caixa "falar com o agente" ao vivo no painel de logs.)

## Data flow (Stop)

Etapa rodando (sessão client registrada) → usuário clica ⏹ Stop → `POST /stop` → `interrupt()` + flag → a etapa
encerra → runner vê `interrupted` → `finish_pause` (card→`paused`, comentário do agente "você interrompeu…") → usuário
corrige na aba Interação → `POST /answer` → `run_pipeline(resume_stage, human_answer)` retoma com a correção.

## Testes

- **Backend unit:** `run_stage` (com `ClaudeSDKClient` stubado) registra/desregistra a sessão e propaga `interrupted`;
  `interrupt(card_id)` sem sessão ativa é no-op seguro; `run_pipeline` com um `stage_fn` que devolve `interrupted=True`
  → card em `paused` com o comentário de interrupção.
- **Smoke real (spike-loop-test):** dispara um card, durante o `implement` clica Stop → card pausa → responde uma
  correção → retoma e conclui. **Só spike-loop-test.**
- **QA visual:** botão Stop aparece só em card `running`; ao parar, card fica âmbar (pausado) e a aba Interação abre.

## Critérios de aceitação (MVP = Stop)

1. Card `running` mostra **⏹ Stop**; clicar interrompe o agente de verdade (`interrupt()`).
2. Ao interromper, o card **pausa** com um comentário do agente pedindo a correção; a aba Interação assume.
3. Responder a correção **retoma** a etapa com a correção no contexto (máquina existente).
4. A pipeline normal (sem Stop) continua idêntica: sequência, fix-loop, pausa por decisão, avanço, commit — sem regressão.
5. Sessão sempre limpa (sem vazar cliente) ao fim do estágio ou no disconnect.

## Fora de escopo (incremento 2 / futuro)

Falar ao vivo sem parar (`/say` + laço multi-turno); trocar modelo/permissão no meio; múltiplas sessões paralelas por
card; histórico de chat separado do thread de comentários.
