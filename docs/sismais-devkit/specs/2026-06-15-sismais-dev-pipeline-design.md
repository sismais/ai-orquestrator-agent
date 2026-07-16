# Sismais Dev — Pipeline SDD Adaptativa (v0.1) — Design

**Data:** 2026-06-15
**Repo:** `sismais/sismais-ai-plugins-private` (privado) · marketplace `sismais-internal`
**Plugin:** `sismais-dev` (namespace de comandos `/sismais-dev-*`)
**Status:** Aprovado para implementação (design)
**Referência arquitetural:** `JotJunior/cstk` (inspiração; não reuso de código) · `anthropics/claude-plugins-official/ralph-loop` (motor de loop, relevante ao sub-projeto 2) · `superpowers` (metodologia: brainstorming / writing-plans / subagent-driven-development — referência de vocabulário e padrões, sem dependência em runtime) · projeto-alvo de prototipagem: `gms-mobile`

## Contexto e objetivo

A Sismais quer tornar a IA o **desenvolvedor/arquiteto principal**, com devs humanos atuando como **supervisores e copilotos** — maximizando a velocidade de entrega de features sem perder qualidade. A revisão humana deve ser **mínima e de alta alavancagem**: aprovar a direção, não revisar cada microdecisão.

Este documento especifica o **primeiro sub-projeto** desse toolkit: uma **pipeline SDD (Spec-Driven Development) adaptativa** que transforma um pedido em linguagem natural em **artefatos de implementação prontos** (spec + plano de arquitetura + lista de tarefas), parando antes de escrever código de feature.

A pipeline nasce como plugin no marketplace privado e é **portável por design**: ela não embute regras de nenhum projeto — lê o `AGENTS.md` e as skills/docs do **projeto-alvo** como fonte de verdade da arquitetura. Apontada para qualquer repositório, ela usa o que aquele repositório já documentou. Quando o motor amadurecer e ficar comprovadamente genérico, o plugin pode graduar para o marketplace público (privado → público é o caminho seguro).

### Por que parar nas tarefas (e não implementar)

A fronteira da v0.1 é deliberada:

- **Fronteira limpa** com o loop autônomo de implementação/review, que é o próximo sub-projeto. Emendar a implementação aqui traria dois subsistemas para o v0.1 de uma vez.
- **É onde a IA-arquiteta mais agrega e mais erra.** Spec/plano/tarefas erradas, implementadas automaticamente, multiplicam o erro. Acertar isso primeiro é o que dá segurança para automatizar a implementação depois.
- **É o ponto certo da revisão humana mínima.** O supervisor aprova *uma vez* a direção da arquitetura (barato, alavancado) em vez de revisar cada mudança de código.

## Decisões fundamentais

- **Pipeline adaptativa, não rígida.** A profundidade escala conforme o pedido — três trilhas (Leve / Padrão / Exploratória). Forçar spec completa num ajuste simples é desperdício; tratar feature complexa como "só tarefas" gera retrabalho.
- **Router automático + override por comando.** Por padrão a triagem decide a trilha; comandos explícitos (`/sismais-dev-feature`, `-fix`, `-brainstorm`) forçam a trilha quando o humano já sabe o que quer.
- **Orquestrador + sub-agentes.** Cada estágio roda como sub-agente com contexto isolado, que reusa as skills de domínio do projeto-alvo. Motor **híbrido**: router e portões humanos são interativos; a sequência travada de cada trilha roda de forma determinística.
- **Pause-or-Decide.** Cada estágio decide sozinho quando há base documental; só pausa e pergunta ao humano quando a ambiguidade é genuína. Decisões automáticas **citam a fonte**.
- **Conhecimento = projeto-alvo.** A "constituição" são as regras do projeto (`AGENTS.md`) e o conhecimento de arquitetura são as `skills/` + `docs/` do projeto. Não recriamos regras.
- **Saída = artefatos + manifesto de handoff.** A pipeline para nas tarefas; não abre PR nem implementa na v0.1, mas deixa o gancho de handoff pronto para o loop futuro.
- **Repo privado primeiro.** Regra da casa: na dúvida, começa privado; mover para público depois é seguro, o inverso não.
- **Self-contained (sem dependência de plugin externo).** O `superpowers` — framework usado para *construir* este plugin (brainstorming/writing-plans/subagent-driven-development) — entra como referência de vocabulário e padrões, **não** como dependência em runtime. Decisão consciente pela portabilidade: a pipeline deve rodar em qualquer projeto sem exigir o superpowers instalado, e sem copiar conteúdo de terceiros. Estágios próprios.

## Escopo da v0.1

### Dentro

1. Plugin `sismais-dev` no padrão Claude Code marketplace, registrado em `sismais-internal`.
2. **Router** de trilha (Leve / Padrão / Exploratória) com override por comando.
3. **Estágios** como sub-agentes: `sismais-dev-specifier`, `sismais-dev-clarifier`, `sismais-dev-planner`, `sismais-dev-tasker`.
4. **Gate Pause-or-Decide** nos estágios que tomam decisão (clarifier e planner).
5. **Comandos:** `/sismais-dev`, `/sismais-dev-feature`, `/sismais-dev-fix`, `/sismais-dev-brainstorm`, `/sismais-dev-resume`.
6. **Artefatos** gravados no projeto-alvo: `spec.md`, `plan.md`, `tasks.md`, `handoff.json`.
7. **Estado leve** (`run.json`) por execução, suficiente para retomada e auditoria.
8. **Reuso do conhecimento do projeto-alvo** (lê `AGENTS.md` + índice de skills + varredura de código).
9. **Sync de prototipagem** para rodar o plugin dentro do `gms-mobile`.
10. Documentação do plugin (SKILL.md, README do plugin) em PT; validador/CI do marketplace passando.

### Fora (sub-projetos futuros)

- **Loop autônomo de implementação/review** (implementa → revisa → corrige → ready + CI verde → humano faz merge). Próximo sub-projeto.
- **Decomposição de produto/épico inteiro** (estilo `agente-00c` do cstk, multi-feature).
- **Painel interativo com tmux** (control plane de sessões paralelas).
- **Substrato de concorrência/durabilidade** (waves, wakeup, lock atômico, índice SQLite cross-feature/`recall`).
- **Auto-PR / auto-merge.**
- **Polimento de instalação multi-projeto / multi-IA.**

## Arquitetura de execução

```
/sismais-dev <pedido>            (ou comando explícito de trilha)
        │
        ▼
   [ ROUTER ]  ── classifica: Leve | Padrão | Exploratória
        │        (lê pedido + AGENTS.md + índice de skills + scan rápido do repo)
        │        registra trilha + justificativa em run.json
        ▼
   ┌─────────────── trilha ───────────────┐
   │ Leve:        tasker (+ mini-plano)    │
   │ Padrão:      specifier → clarifier →  │   cada estágio = sub-agente
   │              planner → tasker         │   contexto isolado, reusa skills
   │ Exploratória: brainstorm → (Padrão)   │   do projeto-alvo
   └───────────────────────────────────────┘
        │   (qualquer estágio pode PAUSE-OR-DECIDE)
        ▼
   artefatos no projeto-alvo + handoff.json   →  PARA (v0.1)
```

- **Interativo onde precisa de julgamento** (router, portões de pausa); **determinístico onde é receita** (a ordem dos estágios de uma trilha).
- O orquestrador é a skill `sismais-dev`; ela despacha os sub-agentes e persiste `run.json` após cada estágio.

### As trilhas

| Trilha | Quando | Estágios | Artefatos |
|-|-|-|-|
| **Leve** | Ajuste/correção pequena, escopo claro | tasker (+ mini-plano embutido) | `tasks.md`, `handoff.json` |
| **Padrão** | Feature com arquitetura a derivar | specifier → clarifier → planner → tasker | `spec.md`, `plan.md`, `tasks.md`, `handoff.json` |
| **Exploratória** | O "o quê" ainda é incerto | brainstorm → cai na Padrão | idem Padrão (+ notas de brainstorm) |

O humano pode **fixar a trilha** (comando) ou **injetar restrições de arquitetura** no pedido; nesse caso os estágios respeitam o que foi dado e só preenchem as lacunas.

## Estágios em detalhe

- **Router** — Entrada: pedido + `AGENTS.md` + índice de skills + scan rápido do repo. Saída: trilha escolhida + justificativa (em `run.json`). Override por comando explícito. *(Decisão de plano: router como lógica dentro da skill orquestradora ou como sub-agente dedicado.)*
- **Specifier** (`sismais-dev-specifier`) — Entrada: pedido + contexto do projeto. Saída: `spec.md` (problema, histórias/critérios de aceite, escopo e não-escopo, regras de negócio). Apoia-se nas skills de domínio do projeto-alvo (ex.: `maissimples-modulo-*` no gms-mobile).
- **Clarifier** (`sismais-dev-clarifier`) — Entrada: `spec.md` + conhecimento do projeto. Aplica **Pause-or-Decide**: para cada ambiguidade, decide com base em evidência (AGENTS.md/docs/código/skills) e **cita a fonte**; só escala ao humano o que não tem base. Saída: decisões registradas (anexadas à spec) + lista de perguntas pendentes (se houver).
- **Planner** (`sismais-dev-planner`) — Entrada: spec + decisões. Saída: `plan.md` — deriva a abordagem técnica **do que já existe** (arquivos/módulos afetados, modelo de dados, reuso de componentes, migrations, cenário offline). Lê código + skills de arquitetura (`screen-patterns`, `supabase`, etc.).
- **Tasker** (`sismais-dev-tasker`) — Entrada: plano (ou, na Leve, o pedido direto). Saída: `tasks.md` (tarefas ordenadas, com critério de aceite e dependências por tarefa) + **`handoff.json`**.

### Pause-or-Decide (resumo)

Heurística adaptada do cstk, simplificada: cada decisão recebe suporte das fontes disponíveis (regras do projeto, docs, código, skills). Com suporte suficiente → **decide** e registra a justificativa com referência. Sem suporte → **pausa** e devolve ao humano um contexto curto do *porquê* não deu para decidir (sem exigir releitura dos artefatos). O peso/limiar exato é decisão de plano.

## Comandos

| Comando | Efeito |
|-|-|
| `/sismais-dev <pedido>` | Entrada padrão; router decide a trilha. |
| `/sismais-dev-feature <ideia>` | Força trilha Padrão. |
| `/sismais-dev-fix <ideia>` | Força trilha Leve. |
| `/sismais-dev-brainstorm <ideia vaga>` | Força trilha Exploratória. |
| `/sismais-dev-resume [run]` | Retoma um run interrompido a partir do `run.json`. |

Namespace `/sismais-dev-*` é o guarda-chuva do suite: o loop de review e o painel, quando vierem, entram com o mesmo prefixo (como plugins irmãos) para uma UX coesa.

## Artefatos e estado

**Onde vivem:** no **projeto-alvo** (são entregáveis dele), em `docs/<raiz-configurável>/<feature-slug>/`. Raiz default proposta: `docs/sismais-dev/` (evita colisão com `docs/sismais-devkit/specs/`); definida ao plugar no gms-mobile e configurável por projeto.

```
docs/sismais-dev/<feature-slug>/
├── spec.md          # trilhas Padrão/Exploratória
├── plan.md          # trilhas Padrão/Exploratória
├── tasks.md         # todas as trilhas
├── handoff.json     # manifesto de handoff (todas as trilhas)
└── run.json         # estado do run
```

**`handoff.json`** — manifesto estruturado para o próximo passo (loop ou humano) continuar sem re-derivar nada. Forma (a fixar no plano): lista de tarefas com `id`, `titulo`, `arquivos_alvo`, `criterio_de_aceite`, `depende_de[]`, e ponteiros para `spec.md`/`plan.md`.

**`run.json`** (estado leve) — `pedido`, `trilha`, `estagios_concluidos[]`, `log_decisoes[]` (com fontes), `perguntas_pendentes[]`, `caminhos_artefatos`. Habilita `/sismais-dev-resume` e auditoria. **Não** há waves/wakeup/lock nem índice cross-feature na v0.1 (sub-projeto "substrato", adiado).

## Conhecimento e constituição (reuso, não recriação)

- **Constituição** = `AGENTS.md` (ou equivalente) do projeto-alvo — regras invioláveis que os estágios respeitam.
- **Conhecimento de arquitetura** = `skills/` + `docs/` do projeto-alvo — consultados pelo planner e specifier.
- Isso é o que torna o plugin portável: a inteligência de domínio fica no projeto, não no plugin. *(Decisão de plano: caminho do arquivo de regras e da raiz de artefatos via pequena config por projeto.)*

## Estrutura do plugin

```
plugins/sismais-dev/
├── .claude-plugin/plugin.json
├── commands/
│   ├── sismais-dev.md
│   ├── sismais-dev-feature.md
│   ├── sismais-dev-fix.md
│   ├── sismais-dev-brainstorm.md
│   └── sismais-dev-resume.md
├── skills/
│   └── sismais-dev/SKILL.md          # orquestrador (cérebro do fluxo)
├── agents/
│   ├── sismais-dev-specifier.md
│   ├── sismais-dev-clarifier.md
│   ├── sismais-dev-planner.md
│   └── sismais-dev-tasker.md
└── scripts/                          # estado leve + helpers
```

Registrado em `.claude-plugin/marketplace.json` (entrada `sismais-dev`). Nome coincide em três lugares (pasta, `plugin.json`, `marketplace.json`), conforme o validador exige. Conteúdo user-facing em PT; código e nomes de arquivo em EN.

## Prototipagem contra o gms-mobile

Um passo de `install`/sync (copiar ou symlink do plugin para `~/.claude/`) permite rodar `sismais-dev` dentro do gms-mobile e validar contra código real. *(Ressalva Windows: symlink exige modo desenvolvedor/admin; alternativa é um pequeno script de cópia. Mecanismo exato decidido no plano.)*

## Decomposição do suite (roadmap)

| Ordem | Sub-projeto | Status |
|-|-|-|
| 1 | **Pipeline SDD adaptativa** (este doc) | em design → implementação |
| 2 | **Loop autônomo de implementação/review** (consome o `handoff.json`) | futuro |
| 3 | **Painel interativo (tmux)** — control plane de sessões paralelas | futuro |
| 4 | **Substrato de durabilidade** (waves/wakeup/lock, recall cross-feature) | futuro |
| — | **Decomposição de produto inteiro** (multi-feature) | futuro |

Nota honesta sobre o painel: o painel do cstk observa *runs isolados em worktrees*; um painel **interativo com tmux** implica rodar vários processos Claude Code reais em panes que o humano anexa — modelo diferente da orquestração in-session desta pipeline. Merece o próprio brainstorm.

Nota sobre o sub-projeto 2 (loop): o plugin oficial `anthropics/claude-plugins-official/ralph-loop` é **base candidata**. Mecanismo: um **Stop hook** intercepta a saída do Claude e re-injeta o prompt, fazendo uma **sessão única** iterar sobre o próprio trabalho (arquivos + git history) até um sentinela de conclusão ou `--max-iterations`. É o caso de uso canônico do loop (implementa → revisa → corrige até passar) e resolve a autonomia sem mensageria entre sessões. Extensões necessárias para nosso uso: **conclusão multi-condição** (DONE / BLOQUEADO / PRECISA-HUMANO — o promise único é limitação conhecida do plugin), o **gate de review como "teste" da iteração**, **CI verde** como condição terminal, e a correção do **path do Stop hook no Windows** (apontar para o `bash.exe` do Git).

## Riscos e mitigações

- **Roteamento errado** (router escolhe trilha rasa demais para um pedido complexo). Mitigação: override por comando sempre disponível; o specifier/planner podem sinalizar "isto exige trilha mais profunda" e o orquestrador re-roteia.
- **Pausa em excesso ou de menos.** Mitigação: calibrar o limiar do Pause-or-Decide numa amostra real do gms-mobile (faz parte do critério de aceitação).
- **Saída genérica** (não usa o conhecimento do projeto). Mitigação: estágios obrigados a citar as skills/docs/código consultados; revisão do critério de aceitação cobre isso.
- **Ferramenta Workflow exige opt-in explícito por invocação.** Mitigação: na v0.1, o motor determinístico pode ser um runner de estágios leve dentro da skill orquestradora (despacho direto de sub-agentes), reservando a ferramenta Workflow para quando o usuário optar. Decisão de plano.
- **Colisão de raiz de artefatos** com `docs/sismais-devkit/specs/` ou outros. Mitigação: raiz configurável; default `docs/sismais-dev/`.
- **Schema exato de comandos/agents empacotados em plugin** a confirmar contra a doc do Claude Code (mesma cautela aplicada no `hello-internal`). Decisão de plano.

## Critérios de aceitação da v0.1

1. Rodar `/sismais-dev-feature` numa feature real do gms-mobile produz `spec.md` + `plan.md` + `tasks.md` + `handoff.json` que um dev (ou o futuro loop) **implementa sem re-derivar a arquitetura** nem voltar para perguntar o básico.
2. O router classifica corretamente uma amostra de pedidos reais (fix → Leve; feature → Padrão; ideia vaga → Exploratória).
3. O Pause-or-Decide pausa **apenas** no que é genuinamente ambíguo na amostra, e as decisões automáticas citam fonte verificável (AGENTS.md/docs/código/skills).
4. Os artefatos seguem as convenções do projeto-alvo (evidência de que as skills de domínio foram usadas, não saída genérica).
5. `/sismais-dev-resume` retoma um run interrompido a partir do `run.json` sem refazer estágios já concluídos.
6. Validador do marketplace passa (`node scripts/validate.mjs .` → `✔`) e CI verde no `main`.
7. Conteúdo user-facing em PT; sem `console.*`/segredos versionados; estrutura do plugin conforme o padrão.

## Questões em aberto (a resolver no plano de implementação)

- Router como lógica na skill orquestradora vs. sub-agente dedicado.
- Forma final do `handoff.json` e do `run.json` (campos e schema).
- Limiar/peso exato do Pause-or-Decide.
- Motor determinístico: runner leve in-skill vs. ferramenta Workflow (considerando o opt-in); o Stop hook do ralph-loop é uma terceira opção, mais relevante ao sub-projeto 2 (loop) que ao pipeline.
- Raiz de artefatos default e mecanismo de config por projeto.
- Mecanismo de sync para prototipagem no Windows (symlink vs. cópia).
- Schema exato de `commands/*.md` e `agents/*.md` empacotados em plugin (confirmar na doc do Claude Code).
