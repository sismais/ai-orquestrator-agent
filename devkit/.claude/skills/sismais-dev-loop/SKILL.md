---
name: sismais-dev-loop
description: Loop autônomo de implementação/review da Sismais. Aciona via /sismais-dev-build ou quando o usuário pede para implementar uma tarefa de forma autônoma e levar até o PR. Implementa numa branch, revisa (independente), corrige, valida, abre PR, espera CI e para no ready-to-merge. NÃO faz merge.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Task
  - Write
---

# Sismais Dev — Loop Autônomo (Orquestrador)

Você conduz um loop que implementa uma tarefa e a leva até **ready-to-merge**, com humano mínimo. VOCÊ (orquestrador) faz todo o git/PR/CI; os sub-agentes editam arquivos e reportam. **Nunca faça merge.** Conhecimento vem do projeto-alvo (`rulesFile`, default `AGENTS.md`).

Script de estado: `${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs` (via Bash com `node`).

## 0. Setup
- Projeto-alvo = diretório atual. Config via `.sismais-dev.json` (defaults: `validateCommand`, `baseBranch`=main, `maxIterations`=6, `useWorktree`=false, `reviewCommand`=null).
- Crie a branch `sismais-dev/<slug>` a partir de `baseBranch` — **nunca** trabalhe na `main`.
- Se `useWorktree`: crie uma worktree irmã para a branch, entre nela, e rode `npm ci` (ou `npm install` se não houver lockfile).
- Init: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" init --repo "<raiz>" --task "<tarefa>" --branch "<branch>" --base "<baseBranch>"` (acrescente `--worktree "<caminho-da-worktree>"` quando `useWorktree` estiver ligado, para o cleanup conseguir removê-la depois). Guarde o `loopPath` impresso.

## 1. Implementa
Despache `sismais-dev-implementer` (Task tool) com a tarefa + `rulesFile` + contexto. Ele edita código+testes e reporta. Você faz o commit na branch.

## 2. Revisa (independente)
Despache `sismais-dev-reviewer` (sub-agente FRESCO) com o diff + `rulesFile`. Ele devolve `blocks`/`fixNow`/`suggestions` como **arrays** de achados. Se `reviewCommand` estiver setado, rode-o em vez disso — ele deve emitir o **mesmo schema JSON** (`blocks`/`fixNow`/`suggestions` como arrays); se não emitir, mapeie o output para esse schema antes de registrar.
Use o `.length` de cada array como contador (B/F/S) ao registrar: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" record-iteration --loop "<loopPath>" --json '{"n":N,"stage":"review","findings":{"blocks":B,"fixNow":F,"suggestions":S},"action":"<...>"}'`.

## 3. Corrige (loop)
Se `blocks` ou `fixNow` > 0: despache o implementer para corrigir SÓ esses achados → commit → volte ao passo 2.
Pare o loop quando: revisor sem `blocks`/`fixNow`, **ou** nº de iterações == `maxIterations` → **PAUSE** ("não convergiu").

## 4. Valida local
Rode o `validateCommand`. Falhou → implementer corrige → commit → revalide (e re-revise se mudou código).

## 5. PR
Push da branch. `gh pr create --draft --base "<baseBranch>" --title "<título>" --body "<descrição gerada>"`. Promova: `gh pr ready <pr>`. Registre: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" set-pr --loop "<loopPath>" --url "<url>"`.

## 6. Espera CI
`gh pr checks <pr> --watch` (o número `<pr>` é o último segmento de `prUrl` — recuperável numa retomada). Para cada check que falhar, despache `sismais-dev-ci-triage` com o log da falha + o diff:
- `related` → implementer corrige → commit → push → re-espere.
- `unrelated`/flaky → registre em `ci` e **não persiga**.
Registre: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" set-ci --loop "<loopPath>" --json '{"status":"green|red|unrelated","checks":[...]}'`.

## 7. Para (ready-to-merge)
Com review limpo + local verde + CI verde: gere a sugestão de merge (default `squash`; descrição = resumo da tarefa + principais mudanças):
`node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" set-merge --loop "<loopPath>" --json '{"type":"squash","description":"<...>"}'` (marca `ready_to_merge`).
Reporte ao usuário: resumo, URL do PR, sugestão de merge + descrição. **Pare. Não faça merge.**

## Pause-or-Decide
Pause (`node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" set-pause --loop "<loopPath>" --json '{"reason":"<...>","context":"<...>"}'`) **só** quando: tarefa ambígua sem base no projeto; achado que exige decisão de produto/arquitetura; ação destrutiva/arriscada (migration/RLS/prod/edge function, conforme `rulesFile`); conflito de merge inseguro; ou não-convergência (teto). Apresente a decisão ao usuário e pare.

## Modo retomada
`/sismais-dev-build-resume <slug>`: ache o run com `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" dir --repo "<raiz>" --slug "<slug>"`, leia o `loop.json` e continue do ponto (status/iterations/ci) sem refazer o concluído.

## Guardrails
Branch de feature sempre; nunca `main`; nunca merge. Respeite os hooks do projeto (`guard-direct-push` — `gh pr ready` não é push; `guard-supabase-writes`). Só persiga falha de CI `related`.
