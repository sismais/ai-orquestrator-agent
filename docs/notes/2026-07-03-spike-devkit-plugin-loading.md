# Spike — DevKit como plugin local (sem copiar pra worktree) + decisão de injeção

**Data:** 2026-07-03 · **Fase 3b-resto (follow-up)** · **Resultado: ✅ plugin CARREGA; mas adotado "sem injeção"**

## Pergunta

O usuário apontou que projetos reais (ex.: GMS Web) **versionam o próprio `.claude`** (skills/agentes
personalizados e de terceiros). O mecanismo antigo (copiar `devkit/.claude` pra dentro da worktree) **poluía a
branch** (o `git add -A` commitava o DevKit) e um "exclude de `.claude`" seria errado (jogaria fora o `.claude`
legítimo do projeto). Como injetar o DevKit sem tocar no `.claude` do projeto?

## O que o spike testou

`plugins=[{"type":"local","path": <devkit empacotado>}]` + `skills="all"`, `cwd` fora da worktree. DevKit
empacotado como plugin: `<root>/.claude-plugin/plugin.json` + `skills/`, `agents/`, `commands/`.

## Resultado

1. **Plugin carrega:** a `SystemMessage` de init listou os comandos como `sismais-devkit:sismais-dev*` e as skills
   como `sismais-devkit:sismais-dev` / `sismais-devkit:sismais-dev-loop`. O agente confirmou vê-los. (~$0.64 via Max.)
2. **Porém `skills="all"` puxa o host inteiro:** apareceram `superpowers:*`, `chrome-devtools-mcp:*`, `supabase:*`,
   `find-skills`, etc. — as skills/plugins globais da **máquina do dev**. Confirma a poluição temida do escopo de
   usuário. Para restringir: `skills=[só as do DevKit]` (o campo `skills` é um filtro de contexto).

## Decisão: **"sem injeção"** (mais simples que o plugin, e resolve o problema do usuário)

O pipeline atual **não precisa das skills do DevKit dentro do agente** — o **backend é o orquestrador** e o papel de
cada estágio é injetado via `system_prompt` (`stage_runner` lê o `.md` do agente de `devkit/.claude/agents`). As skills
que o agente deve usar são as **do próprio projeto**, que já vêm da worktree (checkout). Então:

- **`runner_service.prepare_worktree` deixou de copiar o DevKit.** Worktree = checkout pristino do projeto → o
  `.claude` do projeto fica intacto e é commitado normalmente; o DevKit **nunca** entra na branch. Sem exclude.
- O estágio `plan` **não escreve arquivo** (`.sismais/plan.md`): o planner é read-only e devolve o plano como **texto**,
  que o orquestrador passa pro `implement`. Zero artefato do runner no repo.

## Quando usar o plugin (registrado p/ o futuro)

Se um dia quisermos injetar **skills-padrão Sismais** nos agentes (não as do projeto), o caminho é o plugin local
**provado aqui** — com `skills` filtrado só pro DevKit (evita puxar o host). Empacotamento: `devkit/` com
`.claude-plugin/plugin.json` + `skills/`/`agents/`/`commands/` no root.
