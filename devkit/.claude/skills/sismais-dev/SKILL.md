---
name: sismais-dev
description: Pipeline SDD adaptativa da Sismais. Aciona quando o usuário pede para "implementar", "criar feature", "planejar", "especificar" algo, ou invoca /sismais-dev. Faz triagem da trilha (Leve/Padrão/Exploratória), despacha os estágios e entrega spec + plano + tarefas + handoff. NÃO escreve código de feature — para nos artefatos.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Task
  - Write
---

# Sismais Dev — Orquestrador da Pipeline SDD

Você orquestra uma pipeline que transforma um pedido em **artefatos de implementação** e **para antes de codar a feature**. O conhecimento de arquitetura vem do **projeto-alvo** (não invente regras): leia o arquivo de regras (`rulesFile`, default `AGENTS.md`) e use as skills/docs do projeto.

O script de estado fica em `${CLAUDE_PLUGIN_ROOT}/scripts/run-state.mjs` e é chamado via Bash com `node`.

## 0. Resolver contexto

- Raiz do projeto-alvo = diretório de trabalho atual.
- Config (`artifactsRoot`, `rulesFile`) vem de `.sismais-dev.json` na raiz do projeto-alvo (defaults `docs/sismais-dev` / `AGENTS.md`).
- Leia o `rulesFile` e liste as skills disponíveis (contexto de arquitetura) antes de decidir.

## 1. Roteamento de trilha

Se o usuário veio por um comando explícito (`/sismais-dev-feature|-fix|-brainstorm`), use a trilha forçada. Senão, classifique:

- **Leve** — ajuste/correção pequena, escopo claro, sem decisão de arquitetura nova. Estágios: `tasker`.
- **Padrão** — feature com arquitetura a derivar. Estágios: `specifier` → `clarifier` → `planner` → `tasker`.
- **Exploratória** — o "o quê" ainda é incerto. Faça um brainstorm curto para fixar o objetivo e então siga a trilha **Padrão**.

Critério: na dúvida entre Leve e Padrão, escolha **Padrão** (mais seguro). Registre a trilha e o porquê.

## 2. Inicializar o run

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/run-state.mjs" init --repo "<raiz>" --request "<pedido>" --track <leve|padrao|exploratoria> --reason "<motivo>"
```
Guarde o caminho do `run.json` impresso. O diretório do run é `<artifactsRoot>/<slug>/`.

## 3. Despachar estágios (sequencial)

Para cada estágio da trilha, invoque o sub-agente via **Task tool** passando: o pedido, o caminho do diretório do run, o `rulesFile`, e os artefatos já produzidos. Após cada estágio retornar:

- Grave o artefato do estágio no diretório do run (Write) e registre o caminho:
  `node "${CLAUDE_PLUGIN_ROOT}/scripts/run-state.mjs" set-artifacts --run "<runPath>" --json '{"spec":"spec.md"}'` (ajuste a chave por estágio: `spec`/`plan`/`tasks`/`handoff`).
- `node "${CLAUDE_PLUGIN_ROOT}/scripts/run-state.mjs" mark-stage --run "<runPath>" --stage <specify|clarify|plan|tasks>`.
- Registre decisões e pendências **via CLI** (nunca edite o `run.json` à mão):
  - decisão: `... append-decision --run "<runPath>" --json '{"question":"...","decision":"...","score":2,"sources":["AGENTS.md"],"stage":"clarify"}'`
  - pendências: `... set-pending --run "<runPath>" --json '[{"question":"...","context":"...","stage":"clarify"}]'` (marca `status: paused_for_human` automaticamente).

**Modo retomada:** se o `run.json` já tiver `stagesCompleted`, pule esses estágios e continue do próximo. Use `... dir --repo "<raiz>" --slug "<slug>"` para localizar o diretório do run.

Sub-agentes por estágio: `sismais-dev-specifier`, `sismais-dev-clarifier`, `sismais-dev-planner`, `sismais-dev-tasker`.

## 4. Gate Pause-or-Decide

Se um estágio devolver `pendingQuestions` não vazio, **pare** e apresente ao usuário as perguntas (uma a uma, com opções). Não prossiga para o próximo estágio até resolver — registre-as com `set-pending` (que marca `status: paused_for_human`). Ao receber as respostas, registre-as como decisões (`append-decision`) e continue.

## 5. Encerrar

Quando a trilha terminar, garanta que `handoff.json` existe e marque a conclusão:
`node "${CLAUDE_PLUGIN_ROOT}/scripts/run-state.mjs" set-status --run "<runPath>" --status done`.
Depois mostre ao usuário um resumo curto: trilha usada, artefatos gerados (caminhos), nº de decisões automáticas e de perguntas que precisaram de humano. **Não** abra PR nem implemente código de feature.
