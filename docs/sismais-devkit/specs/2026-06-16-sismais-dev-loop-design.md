# Sismais Dev — Loop Autônomo de Implementação/Review (v1) — Design

**Data:** 2026-06-16
**Repo:** `sismais/sismais-ai-plugins-private` (privado) · marketplace `sismais-internal`
**Plugin:** `sismais-dev-loop` (namespace de comandos `/sismais-dev-*`, irmão de `sismais-dev`)
**Status:** Aprovado para implementação (design)
**Referência:** `anthropics/claude-plugins-official/ralph-loop` (ideias de loop) · `superpowers` (subagent-driven, método) · sub-projeto 1 `sismais-dev` (pipeline; produz `handoff.json` que será fonte futura)

## Contexto e objetivo

Segundo sub-projeto do toolkit de IA-dev da Sismais. Realiza o **loop autônomo "dois devs"**: a IA implementa uma tarefa, um **revisor independente** avalia, a IA corrige, re-revisa até convergir, valida, abre PR, espera o CI e **para no ready-to-merge** — com **interação humana mínima**, pausando só no que de fato exige decisão humana. O humano aprova e faz o merge; **o loop nunca faz merge**.

Consome o que o sub-projeto 1 não cobre (a implementação): a pipeline para nas tarefas; este loop as executa. No v1 a entrada é uma **tarefa direta**; consumir o `handoff.json` da pipeline é um modo posterior.

Self-contained e portátil, como o sub-projeto 1: o conhecimento de arquitetura/regras vem do **projeto-alvo** (`AGENTS.md` + skills/docs), não do plugin; sem dependência de plugin externo em runtime.

## Decisões fundamentais

- **Entrada = tarefa direta** (`/sismais-dev-build "<tarefa>"`). `handoff.json` da pipeline = fonte futura.
- **Motor = orquestrador in-session + revisor independente.** Uma skill conduz o loop e despacha sub-agentes frescos por etapa; o **revisor é sempre um sub-agente independente do implementador** (contexto isolado = "segundo dev" de verdade). Pega ideias do ralph-loop (sentinela de conclusão, teto de iterações, "falhas são dados") **sem** o Stop-hook.
- **Revisor built-in com grounding.** Lê `rulesFile` + skills + diff, devolve achados em baldes (bloqueia merge / corrige agora / sugestão). Opcionalmente delega ao `reviewCommand` do projeto (ex.: `/maissimples-review-pr`) quando configurado.
- **Terminal completo até ready-to-merge.** branch → review limpo → validação local → PR draft → ready → espera CI → corrige falhas de CI **relacionadas ao diff** → para no ready-to-merge sugerindo tipo de merge + descrição. **Nunca faz merge.**
- **Pause-or-Decide.** Autonomia máxima; pausa só em decisão genuína de humano.
- **Worktree opt-in.** `useWorktree` (default off no v1); quando ligado, o loop cria a worktree no setup; destruição via comando separado (sem auto-destroy).
- **Git centralizado no orquestrador.** Branch, commits, push, PR e espera-CI são feitos pelo orquestrador (com guardrails); os sub-agentes editam arquivos e reportam.
- **Self-contained** (sem dependência de plugin externo).

## Escopo da v1

### Dentro

1. Plugin `sismais-dev-loop` no marketplace `sismais-internal`.
2. Comandos: `/sismais-dev-build <tarefa>`, `/sismais-dev-build-resume <slug>`, `/sismais-dev-build-cleanup <slug>`.
3. Skill orquestradora do loop (setup → implementa → revisa → corrige → valida → PR → ready → espera CI → para).
4. Sub-agentes: `sismais-dev-implementer` (implementa/corrige), `sismais-dev-reviewer` (review independente, grounding), `sismais-dev-ci-triage` (falha de CI é relacionada ao diff?).
5. `loop-state.mjs` (+ testes) — ciclo de vida do `loop.json`.
6. Pause-or-Decide nos pontos de decisão genuína.
7. Worktree opt-in + cleanup por comando.
8. Sugestão de tipo de merge + descrição no encerramento.
9. Guardrails (branch-only, never-merge, respeita hooks, teto de iterações, CI só relacionado ao diff).

### Fora (futuro)

- **Notificação da pausa ao humano** (ver seção própria — direção registrada, não implementada).
- **Auto-merge** (nunca; humano sempre faz).
- **Consumir `handoff.json`** da pipeline (modo posterior; v1 é tarefa direta).
- **Durabilidade via Stop-hook / sobreviver a restart** (orquestrador roda in-session).
- **Auto-destroy de worktree no merge** (cleanup é por comando).
- **Loops paralelos / multi-feature** e o painel de acompanhamento (sub-projeto 3).

## Arquitetura de execução

```
/sismais-dev-build "<tarefa>"
        │
        ▼
[0] SETUP    resolve projeto-alvo + rulesFile + config; cria branch de feature
             (nunca main; respeita hooks); se useWorktree, cria worktree + npm install;
             inicializa loop.json
        ▼
[1] IMPLEMENTA   sub-agente implementer (grounding) edita código+testes → orquestrador commita
        ▼
[2] REVISA       sub-agente reviewer INDEPENDENTE (rulesFile+skills+diff) → baldes de achados
        ▼
[3] CORRIGE      há bloqueia/corrige-agora? → implementer corrige → volta a [2]
   (loop até)    revisor limpo  OU  teto de iterações (→ PAUSE)
        ▼
[4] VALIDA LOCAL  roda validateCommand (lint/tsc/test). Falhou → corrige → revalida
        ▼
[5] PR           push; abre PR draft (gh) com descrição gerada; promove a ready
        ▼
[6] ESPERA CI    gh pr checks. Falha relacionada ao diff (ci-triage) → corrige → push → re-espera
                 Falha não-relacionada/flaky → registra e NÃO persegue
        ▼
[7] PARA         review limpo + local verde + CI verde → status ready_to_merge
                 reporta resumo + sugestão de merge (tipo + descrição). Humano faz o merge.
```

Interativo onde precisa de julgamento (Pause-or-Decide); determinístico no encadeamento das etapas. O orquestrador persiste `loop.json` após cada transição.

## Pause-or-Decide

Pausa (status `paused_for_human`, grava `pause: {reason, context}`) **apenas** quando:

- A tarefa é ambígua e não há base no projeto para decidir.
- Um achado de review exige decisão de produto/arquitetura (não é correção mecânica).
- A ação é **destrutiva/arriscada** conforme o `rulesFile` (migration, mudança de RLS, fix em produção, deploy de edge function).
- Há conflito de merge que não dá para resolver com segurança.
- O loop **não converge** (bateu o teto de iterações).

Caso contrário, decide e segue (autonomia). A notificação dessa pausa é tratada na seção "Notificação" (futuro).

## Worktree (opt-in)

- `useWorktree: true` → no SETUP o loop cria uma worktree irmã para a branch de feature e roda lá (isolando a árvore principal — relevante porque o repo é editado em paralelo por outras ferramentas). Custo aceito: a worktree não tem `node_modules`, então o loop roda `npm install` nela antes do `validateCommand` (custo único por run).
- `useWorktree: false` (default v1) → roda na branch in-place.
- **Cleanup** via `/sismais-dev-build-cleanup <slug>`: remove a worktree e, opcionalmente, a branch local. Rodado por você **após o merge** (o loop para antes do merge, então não há auto-destroy).

## Guardrails

- Branch de feature sempre; **nunca** opera/commita em `main`. Respeita `guard-direct-push` (push vai pra branch; `gh pr ready` não é push) e `guard-supabase-writes`.
- **Nunca faz merge** — para no ready-to-merge.
- Teto de iterações (`maxIterations`) para o fix loop e para o ciclo de CI.
- CI: só corrige falhas que o `ci-triage` julga **relacionadas ao diff** do PR.

## Estrutura do plugin

```
plugins/sismais-dev-loop/
├── .claude-plugin/plugin.json
├── skills/sismais-dev-loop/SKILL.md        # orquestrador do loop
├── agents/
│   ├── sismais-dev-implementer.md          # implementa/corrige
│   ├── sismais-dev-reviewer.md             # review independente, grounding
│   └── sismais-dev-ci-triage.md            # falha de CI é relacionada ao diff?
├── commands/
│   ├── sismais-dev-build.md
│   ├── sismais-dev-build-resume.md
│   └── sismais-dev-build-cleanup.md
├── scripts/
│   ├── loop-state.mjs                      # ciclo de vida do loop.json (lib + CLI)
│   └── loop-state.test.mjs
└── README.md
```
Registrado em `.claude-plugin/marketplace.json` (entrada `sismais-dev-loop`). Conteúdo user-facing em PT; código/nomes em EN. Validador do marketplace deve passar.

## Config e estado

**Config** — estende o `.sismais-dev.json` do projeto-alvo (compartilhado com a pipeline). Chaves novas (todas com default):
- `validateCommand` (default `npm run lint && npx tsc --noEmit && npm test`)
- `baseBranch` (default `main`)
- `maxIterations` (default a definir no plano, ex. 6)
- `reviewCommand` (opcional; quando setado, delega o review a ele)
- `useWorktree` (default `false`)
- *(reservado, não implementado no v1)* `notifyCommand`

**Estado (`loop.json`)** — gravado no diretório de artefatos do run (`<artifactsRoot>/<taskSlug>/loop.json`):
- `version`, `task`, `taskSlug`, `branch`, `baseBranch`, `worktreePath` (se usada)
- `iterations[]`: `{ n, stage, findings: {blocks, fixNow, suggestions}, action }`
- `ci`: `{ status: pending|green|red|unrelated, checks: [] }`
- `prUrl`, `status` (`in_progress`|`paused_for_human`|`ready_to_merge`)
- `pause`: `{ reason, context }` (quando pausado)
- `mergeSuggestion`: `{ type: "squash"|"merge", description }` (no ready_to_merge)

`loop-state.mjs` expõe funções testáveis (slug, resolveConfig, initLoop/readLoop, recordIteration, setCI, setPR, setStatus, setPause, setMergeSuggestion) + uma CLL que o orquestrador chama via Bash. Self-contained (não reusa o `run-state.mjs` do outro plugin, para manter fronteira limpa).

## Notificação ao humano (futuro — registrado, não implementado no v1)

Quando o loop pausa, ele já grava `status: paused_for_human` + `pause` no `loop.json` (fonte única). Entrega:

- **Curto prazo (sem código no loop):** o **hook nativo de `Notification` do Claude Code** dispara ao aguardar entrada do usuário — uma pausa do loop deve acioná-lo; o usuário o configura (toast/som/Slack/script). *(Confirmar o gatilho exato.)*
- **Ponto reservado `notifyCommand`:** comando configurável invocado na pausa com o contexto (motivo, slug, URL do PR). Mantém o loop **agnóstico de canal**; backends: ferramenta PushNotification, webhook Slack/WhatsApp, etc.
- **Painel (sub-projeto 3):** surfacearia pausas de vários loops num lugar só.

## Riscos e mitigações

- **Acoplamento a gh/CI** (menos portátil, mais lento/frágil). Mitigação: as etapas gh/CI são gated por config; falhas de CI não-relacionadas são registradas, não perseguidas; em ambiente sem gh, o loop pode parar antes do PR (degradação clara).
- **Revisão "complacente"** (revisor concordando consigo mesmo). Mitigação: revisor é sub-agente **independente** com mandato de cético e grounding obrigatório (cita fonte); o fix loop só fecha quando ele não tem mais bloqueios.
- **Não-convergência / loop infinito.** Mitigação: `maxIterations`; ao estourar, **pausa** (não decide sozinho).
- **Ações destrutivas autônomas** (migration/RLS/prod). Mitigação: Pause-or-Decide obriga pausa nesses casos; hooks do projeto bloqueiam writes perigosos.
- **Custo de `npm install` na worktree.** Mitigação: worktree é opt-in; custo único por run; documentado.
- **Validação plena difícil em unit test** (gh/CI são reais). Mitigação: `loop-state.mjs` é unit-testado; o fluxo gh/CI é validado no smoke real (no fim, por você).

## Critérios de aceitação da v1

1. `/sismais-dev-build "<tarefa real>"` no gms-mobile gera branch com código+testes, PR draft→ready, CI verde, e para com sugestão de merge — **sem você tocar**, exceto onde pausa por decisão genuína.
2. O revisor é um sub-agente **independente** e cita regras/fonte; o fix loop converge ou pausa no teto.
3. CI: corrige falha **relacionada** ao diff; **registra e ignora** falha não-relacionada/flaky.
4. Pausa só em decisão genuína (tarefa ambígua → pausa; tarefa clara → não pausa).
5. Nunca toca `main`; nunca faz merge; respeita `guard-direct-push`/`guard-supabase-writes`.
6. Com `useWorktree: true`, o loop roda numa worktree isolada e `/sismais-dev-build-cleanup` a remove.
7. `loop-state.mjs` testado (`node --test`); validador do marketplace OK.

## Questões em aberto (a resolver no plano)

- Valor default de `maxIterations` e como contar iterações (por rodada de review vs total).
- Forma exata da "sugestão de merge" (heurística squash vs merge) e do texto de descrição.
- Como o orquestrador resolve o caminho do plugin/scripts (`${CLAUDE_PLUGIN_ROOT}`, como no sub-projeto 1).
- Estratégia de espera de CI (`gh pr checks --watch` vs polling) e timeouts.
- Critério prático do `ci-triage` para "relacionado ao diff".
- Schema exato de `loop.json` e da CLI de `loop-state.mjs`.
- Como/onde rodar `npm install` na worktree de forma robusta no Windows.
