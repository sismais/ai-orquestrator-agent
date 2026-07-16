# Sismais Dev — Pipeline SDD Adaptativa (v0.1) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o plugin `sismais-dev` (marketplace privado `sismais-internal`) que transforma um pedido em linguagem natural em artefatos de implementação (spec + plano + tarefas + handoff), com router de trilha adaptativa e gate Pause-or-Decide, parando antes de escrever código de feature.

**Architecture:** Plugin Claude Code com uma skill orquestradora (`sismais-dev`) que faz o roteamento de trilha e despacha sub-agentes de estágio (`specifier`/`clarifier`/`planner`/`tasker`) via Task tool, persistindo estado num `run.json` por execução. A lógica determinística e testável (slug, config, ciclo de vida do `run.json`) vive num módulo Node `run-state.mjs`. O conhecimento de arquitetura vem do projeto-alvo (`AGENTS.md` + skills/docs), não do plugin.

**Tech Stack:** Claude Code plugin (markdown: skill/agents/commands) · Node.js 20+ ESM (`run-state.mjs`, testes via `node --test`) · validador de marketplace existente (`scripts/validate.mjs`).

---

## Decisões travadas (resolvem as "questões em aberto" do spec)

- **Router:** lógica dentro da skill `sismais-dev` (sem agente dedicado). Comandos explícitos forçam a trilha.
- **Motor determinístico:** runner leve in-skill — a skill despacha os sub-agentes de estágio via Task tool, em sequência, conforme a trilha. **Sem** ferramenta Workflow e **sem** Stop hook no v0.1 (Stop hook fica para o sub-projeto 2).
- **Estado/config:** módulo `run-state.mjs` (testável) + CLI que a skill chama via Bash.
- **Raiz de artefatos:** `docs/sismais-dev/<feature-slug>/` no projeto-alvo, configurável por `.sismais-dev.json` na raiz do projeto-alvo (`artifactsRoot`, `rulesFile`; defaults `docs/sismais-dev` e `AGENTS.md`).
- **Pause-or-Decide:** score 0–3 sobre 4 fontes (rulesFile, docs, código, skills); `>= 2` decide e cita fonte; `< 2` pausa.
- **Prototipagem:** marketplace local `directory` source apontando para o repo privado (sem depender de push), conforme `CONTRIBUTING.md`.

## Mapa de arquivos (no repo `sismais-ai-plugins-private`)

```
plugins/sismais-dev/
├── .claude-plugin/plugin.json              # manifesto do plugin
├── skills/sismais-dev/SKILL.md             # orquestrador: router + dispatch + Pause-or-Decide
├── agents/
│   ├── sismais-dev-specifier.md            # ideia → spec.md
│   ├── sismais-dev-clarifier.md            # resolve ambiguidades (Pause-or-Decide)
│   ├── sismais-dev-planner.md              # spec → plan.md (deriva arquitetura do projeto)
│   └── sismais-dev-tasker.md               # plan → tasks.md + handoff.json
├── commands/
│   ├── sismais-dev.md                      # entrada padrão (router decide)
│   ├── sismais-dev-feature.md              # força trilha Padrão
│   ├── sismais-dev-fix.md                  # força trilha Leve
│   ├── sismais-dev-brainstorm.md           # força trilha Exploratória
│   └── sismais-dev-resume.md               # retoma run a partir do run.json
└── scripts/
    ├── run-state.mjs                       # slug, config, ciclo de vida do run.json (lib + CLI)
    └── run-state.test.mjs                  # testes node --test
```
- Modificar: `.claude-plugin/marketplace.json` (raiz do repo) — adicionar entrada `sismais-dev`.

Responsabilidades: `run-state.mjs` concentra toda decisão determinística (paths, JSON). Os arquivos `.md` são prompts (geração de conteúdo). O validador só inspeciona `skills/*/SKILL.md` — `commands/` e `agents/` são livres.

## Schemas (referência para todas as tasks)

**`run.json`** (em `docs/sismais-dev/<slug>/run.json`):
```json
{
  "version": 1,
  "request": "<pedido original>",
  "track": "leve|padrao|exploratoria",
  "trackReason": "<por que o router escolheu>",
  "featureSlug": "<slug>",
  "stagesCompleted": [],
  "decisions": [],
  "pendingQuestions": [],
  "artifacts": {},
  "status": "in_progress"
}
```
- `decisions[]`: `{ "question", "decision", "score", "sources": [], "stage" }`
- `pendingQuestions[]`: `{ "question", "context", "stage" }`
- `artifacts`: `{ "spec": "spec.md", "plan": "plan.md", "tasks": "tasks.md", "handoff": "handoff.json" }`
- `status`: `in_progress` | `paused_for_human` | `done`

**`handoff.json`** (em `docs/sismais-dev/<slug>/handoff.json`):
```json
{
  "version": 1,
  "featureSlug": "<slug>",
  "spec": "spec.md",
  "plan": "plan.md",
  "tasks": [
    { "id": "T1", "titulo": "...", "arquivosAlvo": ["src/..."], "criterioDeAceite": "...", "dependeDe": [] }
  ]
}
```

**`.sismais-dev.json`** (raiz do projeto-alvo, opcional):
```json
{ "artifactsRoot": "docs/sismais-dev", "rulesFile": "AGENTS.md" }
```

---

## Task 1: Scaffold do plugin + registro no marketplace

**Files:**
- Create: `plugins/sismais-dev/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Criar `plugin.json`**

`plugins/sismais-dev/.claude-plugin/plugin.json`:
```json
{
  "name": "sismais-dev",
  "version": "0.1.0",
  "description": "Pipeline SDD adaptativa — transforma um pedido em spec + plano + tarefas + handoff, com router de trilha e Pause-or-Decide.",
  "author": { "name": "Sismais" }
}
```

- [ ] **Step 2: Registrar no `marketplace.json`**

Adicionar ao array `plugins[]` em `.claude-plugin/marketplace.json` (após a entrada `hello-internal`):
```json
{
  "name": "sismais-dev",
  "source": "./plugins/sismais-dev",
  "description": "Pipeline SDD adaptativa — pedido em linguagem natural vira spec + plano + tarefas + handoff.",
  "version": "0.1.0",
  "category": "workflow",
  "tags": ["sdd", "pipeline", "internal", "orchestration"]
}
```

- [ ] **Step 3: Criar diretórios vazios necessários**

Run:
```bash
mkdir -p plugins/sismais-dev/skills/sismais-dev plugins/sismais-dev/agents plugins/sismais-dev/commands plugins/sismais-dev/scripts
```

- [ ] **Step 4: Validar marketplace**

Run: `node scripts/validate.mjs .`
Expected: `✔ Validação OK`. Correção de premissa (verificada na execução): o validador **pula** `SKILL.md` ausente (`validate.mjs`: `if (!existsSync(skillMd)) continue;`) — só falha se um `SKILL.md` existir sem frontmatter. O scaffold já valida limpo; confirme apenas que o JSON do marketplace/plugin é válido e o 3-way match (`sismais-dev`) bate.

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat(sismais-dev): scaffold do plugin e registro no marketplace"
```

---

## Task 2: `run-state.mjs` — `slugify` (TDD)

**Files:**
- Create: `plugins/sismais-dev/scripts/run-state.test.mjs`
- Create: `plugins/sismais-dev/scripts/run-state.mjs`

- [ ] **Step 1: Escrever teste que falha**

`plugins/sismais-dev/scripts/run-state.test.mjs`:
```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { slugify } from './run-state.mjs';

test('slugify gera kebab-case ascii', () => {
  assert.equal(slugify('Desconto por item no PDV'), 'desconto-por-item-no-pdv');
});

test('slugify remove acentos', () => {
  assert.equal(slugify('Emissão de Nota Fiscal'), 'emissao-de-nota-fiscal');
});

test('slugify colapsa separadores e apara bordas', () => {
  assert.equal(slugify('  A//B  C '), 'a-b-c');
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: FAIL — `Cannot find module './run-state.mjs'` (arquivo ainda não existe).

- [ ] **Step 3: Implementar `slugify`**

`plugins/sismais-dev/scripts/run-state.mjs`:
```js
import fs from 'node:fs';
import path from 'node:path';

export function slugify(text) {
  return String(text)
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/scripts/run-state.mjs plugins/sismais-dev/scripts/run-state.test.mjs
git commit -m "feat(sismais-dev): slugify de feature em run-state"
```

---

## Task 3: `run-state.mjs` — `resolveConfig` (TDD)

**Files:**
- Modify: `plugins/sismais-dev/scripts/run-state.test.mjs`
- Modify: `plugins/sismais-dev/scripts/run-state.mjs`

- [ ] **Step 1: Adicionar teste que falha**

Acrescentar ao topo de `run-state.test.mjs` (após os imports existentes) o import e, ao final do arquivo, os testes:
```js
import os from 'node:os';
import fs from 'node:fs';
import path from 'node:path';
import { resolveConfig } from './run-state.mjs';

function tmpRepo() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'sismais-dev-'));
}

test('resolveConfig usa defaults quando nao ha .sismais-dev.json', () => {
  const repo = tmpRepo();
  assert.deepEqual(resolveConfig(repo), { artifactsRoot: 'docs/sismais-dev', rulesFile: 'AGENTS.md' });
});

test('resolveConfig mescla overrides do arquivo sobre os defaults', () => {
  const repo = tmpRepo();
  fs.writeFileSync(path.join(repo, '.sismais-dev.json'), JSON.stringify({ rulesFile: 'CLAUDE.md' }));
  assert.deepEqual(resolveConfig(repo), { artifactsRoot: 'docs/sismais-dev', rulesFile: 'CLAUDE.md' });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: FAIL — `resolveConfig is not a function` (export ausente).

- [ ] **Step 3: Implementar `resolveConfig`**

Acrescentar a `run-state.mjs`:
```js
const DEFAULT_CONFIG = { artifactsRoot: 'docs/sismais-dev', rulesFile: 'AGENTS.md' };

export function resolveConfig(repoRoot) {
  const cfgPath = path.join(repoRoot, '.sismais-dev.json');
  if (!fs.existsSync(cfgPath)) return { ...DEFAULT_CONFIG };
  const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  return { ...DEFAULT_CONFIG, ...raw };
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: PASS (5 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/scripts/run-state.mjs plugins/sismais-dev/scripts/run-state.test.mjs
git commit -m "feat(sismais-dev): resolveConfig com defaults e override por projeto"
```

---

## Task 4: `run-state.mjs` — `runDir`, `initRun`, `readRun` (TDD)

**Files:**
- Modify: `plugins/sismais-dev/scripts/run-state.test.mjs`
- Modify: `plugins/sismais-dev/scripts/run-state.mjs`

- [ ] **Step 1: Adicionar teste que falha**

Acrescentar ao final de `run-state.test.mjs`:
```js
import { runDir, initRun, readRun } from './run-state.mjs';

test('runDir respeita artifactsRoot configurado', () => {
  const repo = tmpRepo();
  fs.writeFileSync(path.join(repo, '.sismais-dev.json'), JSON.stringify({ artifactsRoot: 'docs/x' }));
  assert.equal(runDir(repo, 'minha-feature'), path.join(repo, 'docs/x', 'minha-feature'));
});

test('initRun cria o diretorio e grava run.json com status in_progress', () => {
  const repo = tmpRepo();
  const runPath = initRun(repo, {
    request: 'Desconto por item', track: 'padrao', trackReason: 'feature nova', featureSlug: 'desconto-por-item'
  });
  const run = readRun(runPath);
  assert.equal(run.version, 1);
  assert.equal(run.track, 'padrao');
  assert.equal(run.featureSlug, 'desconto-por-item');
  assert.equal(run.status, 'in_progress');
  assert.deepEqual(run.stagesCompleted, []);
  assert.ok(fs.existsSync(runPath));
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: FAIL — `runDir is not a function`.

- [ ] **Step 3: Implementar `runDir`, `initRun`, `readRun`, `writeRun`**

Acrescentar a `run-state.mjs`:
```js
export function runDir(repoRoot, slug) {
  const { artifactsRoot } = resolveConfig(repoRoot);
  return path.join(repoRoot, artifactsRoot, slug);
}

function writeRun(runPath, run) {
  fs.writeFileSync(runPath, JSON.stringify(run, null, 2) + '\n');
}

export function readRun(runPath) {
  return JSON.parse(fs.readFileSync(runPath, 'utf8'));
}

export function initRun(repoRoot, { request, track, trackReason, featureSlug }) {
  const dir = runDir(repoRoot, featureSlug);
  fs.mkdirSync(dir, { recursive: true });
  const run = {
    version: 1, request, track, trackReason, featureSlug,
    stagesCompleted: [], decisions: [], pendingQuestions: [],
    artifacts: {}, status: 'in_progress'
  };
  const runPath = path.join(dir, 'run.json');
  writeRun(runPath, run);
  return runPath;
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: PASS (7 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/scripts/run-state.mjs plugins/sismais-dev/scripts/run-state.test.mjs
git commit -m "feat(sismais-dev): initRun/readRun e resolucao de diretorio do run"
```

---

## Task 5: `run-state.mjs` — mutações de estado (TDD)

**Files:**
- Modify: `plugins/sismais-dev/scripts/run-state.test.mjs`
- Modify: `plugins/sismais-dev/scripts/run-state.mjs`

- [ ] **Step 1: Adicionar teste que falha**

Acrescentar ao final de `run-state.test.mjs`:
```js
import { markStage, appendDecision, setPending, setStatus, setArtifacts } from './run-state.mjs';

function freshRun() {
  const repo = tmpRepo();
  return initRun(repo, { request: 'x', track: 'padrao', trackReason: 'r', featureSlug: 'f' });
}

test('markStage acrescenta sem duplicar', () => {
  const runPath = freshRun();
  markStage(runPath, 'specify');
  markStage(runPath, 'specify');
  markStage(runPath, 'clarify');
  assert.deepEqual(readRun(runPath).stagesCompleted, ['specify', 'clarify']);
});

test('appendDecision registra decisao com fontes', () => {
  const runPath = freshRun();
  appendDecision(runPath, { question: 'q', decision: 'd', score: 2, sources: ['AGENTS.md'], stage: 'clarify' });
  assert.equal(readRun(runPath).decisions.length, 1);
  assert.equal(readRun(runPath).decisions[0].score, 2);
});

test('setPending com perguntas marca status paused_for_human', () => {
  const runPath = freshRun();
  setPending(runPath, [{ question: 'q', context: 'c', stage: 'clarify' }]);
  assert.equal(readRun(runPath).status, 'paused_for_human');
});

test('setPending vazio nao rebaixa status', () => {
  const runPath = freshRun();
  setStatus(runPath, 'done');
  setPending(runPath, []);
  assert.equal(readRun(runPath).status, 'done');
});

test('setArtifacts mescla ponteiros', () => {
  const runPath = freshRun();
  setArtifacts(runPath, { spec: 'spec.md' });
  setArtifacts(runPath, { plan: 'plan.md' });
  assert.deepEqual(readRun(runPath).artifacts, { spec: 'spec.md', plan: 'plan.md' });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: FAIL — `markStage is not a function`.

- [ ] **Step 3: Implementar as mutações**

Acrescentar a `run-state.mjs`:
```js
export function markStage(runPath, stage) {
  const run = readRun(runPath);
  if (!run.stagesCompleted.includes(stage)) run.stagesCompleted.push(stage);
  writeRun(runPath, run);
  return run;
}

export function appendDecision(runPath, decision) {
  const run = readRun(runPath);
  run.decisions.push(decision);
  writeRun(runPath, run);
  return run;
}

export function setPending(runPath, questions) {
  const run = readRun(runPath);
  run.pendingQuestions = questions;
  if (questions.length) run.status = 'paused_for_human';
  writeRun(runPath, run);
  return run;
}

export function setStatus(runPath, status) {
  const run = readRun(runPath);
  run.status = status;
  writeRun(runPath, run);
  return run;
}

export function setArtifacts(runPath, artifacts) {
  const run = readRun(runPath);
  run.artifacts = { ...run.artifacts, ...artifacts };
  writeRun(runPath, run);
  return run;
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: PASS (12 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/scripts/run-state.mjs plugins/sismais-dev/scripts/run-state.test.mjs
git commit -m "feat(sismais-dev): mutacoes de estado do run (stage/decisao/pending/status/artifacts)"
```

---

## Task 6: CLI de `run-state.mjs` (para a skill chamar via Bash)

**Files:**
- Modify: `plugins/sismais-dev/scripts/run-state.mjs`
- Modify: `plugins/sismais-dev/scripts/run-state.test.mjs`

- [ ] **Step 1: Adicionar teste de integração da CLI que falha**

Acrescentar ao final de `run-state.test.mjs`:
```js
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const CLI = fileURLToPath(new URL('./run-state.mjs', import.meta.url));

test('CLI init grava run.json e imprime o caminho', () => {
  const repo = tmpRepo();
  const out = execFileSync('node', [CLI, 'init', '--repo', repo, '--request', 'Teste CLI', '--track', 'leve'], { encoding: 'utf8' }).trim();
  assert.ok(out.endsWith('run.json'));
  assert.equal(readRun(out).track, 'leve');
  assert.equal(readRun(out).featureSlug, 'teste-cli');
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: FAIL — a CLI ainda não imprime nada / sai com erro (sem bloco CLI).

- [ ] **Step 3: Implementar o bloco CLI no fim de `run-state.mjs`**

Acrescentar ao final de `run-state.mjs`:
```js
function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, '')] = argv[i + 1];
  return args;
}

function isMain() {
  return fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || '');
}

if (isMain()) {
  const [cmd, ...rest] = process.argv.slice(2);
  const a = parseArgs(rest);
  if (cmd === 'init') {
    const featureSlug = a.slug || slugify(a.request);
    const runPath = initRun(a.repo, { request: a.request, track: a.track, trackReason: a.reason || '', featureSlug });
    process.stdout.write(runPath + '\n');
  } else if (cmd === 'mark-stage') {
    markStage(a.run, a.stage); process.stdout.write('ok\n');
  } else if (cmd === 'set-status') {
    setStatus(a.run, a.status); process.stdout.write('ok\n');
  } else if (cmd === 'dir') {
    process.stdout.write(runDir(a.repo, a.slug) + '\n');
  } else {
    process.stderr.write(`comando desconhecido: ${cmd}\n`); process.exit(1);
  }
}
```
E adicionar ao topo de `run-state.mjs` (junto aos imports):
```js
import { fileURLToPath } from 'node:url';
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev/scripts/run-state.test.mjs`
Expected: PASS (13 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev/scripts/run-state.mjs plugins/sismais-dev/scripts/run-state.test.mjs
git commit -m "feat(sismais-dev): CLI de run-state (init/mark-stage/set-status/dir)"
```

---

## Task 7: Skill orquestradora `sismais-dev` (router + dispatch)

**Files:**
- Create: `plugins/sismais-dev/skills/sismais-dev/SKILL.md`

- [ ] **Step 1: Criar a SKILL.md**

`plugins/sismais-dev/skills/sismais-dev/SKILL.md`:
```markdown
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

## 0. Resolver contexto

- Raiz do projeto-alvo = diretório de trabalho atual.
- Config: rode `node <PLUGIN>/scripts/run-state.mjs dir --repo <raiz> --slug _probe` apenas se precisar do path; a config (`artifactsRoot`, `rulesFile`) vem de `.sismais-dev.json` na raiz (defaults `docs/sismais-dev` / `AGENTS.md`).
- Leia o `rulesFile` e liste as skills disponíveis (contexto de arquitetura).

## 1. Roteamento de trilha

Se o usuário veio por um comando explícito (`/sismais-dev-feature|-fix|-brainstorm`), use a trilha forçada. Senão, classifique:

- **Leve** — ajuste/correção pequena, escopo claro, sem decisão de arquitetura nova. Estágios: `tasker`.
- **Padrão** — feature com arquitetura a derivar. Estágios: `specifier` → `clarifier` → `planner` → `tasker`.
- **Exploratória** — o "o quê" ainda é incerto. Faça um brainstorm curto (use a skill de brainstorming se disponível) para fixar o objetivo e então siga a trilha **Padrão**.

Critério: na dúvida entre Leve e Padrão, escolha **Padrão** (mais seguro). Registre a trilha e o porquê.

## 2. Inicializar o run

```bash
node <PLUGIN>/scripts/run-state.mjs init --repo <raiz> --request "<pedido>" --track <leve|padrao|exploratoria> --reason "<motivo>"
```
Guarde o caminho do `run.json` impresso. O diretório do run é `docs/sismais-dev/<slug>/`.

## 3. Despachar estágios (sequencial)

Para cada estágio da trilha, invoque o sub-agente via **Task tool** passando: o pedido, o caminho do diretório do run, o `rulesFile`, e os artefatos já produzidos. Após cada estágio retornar:

- Grave o artefato do estágio no diretório do run (Write).
- `node <PLUGIN>/scripts/run-state.mjs mark-stage --run <runPath> --stage <specify|clarify|plan|tasks>`.
- Registre decisões automáticas (campo `decisions`) e perguntas pendentes (campo `pendingQuestions`) que o estágio devolveu, editando o `run.json` (Write) conforme o schema.

Sub-agentes por estágio: `sismais-dev-specifier`, `sismais-dev-clarifier`, `sismais-dev-planner`, `sismais-dev-tasker`.

## 4. Gate Pause-or-Decide

Se um estágio devolver `pendingQuestions` não vazio, **pare** e apresente ao usuário as perguntas (uma a uma, com opções). Não prossiga para o próximo estágio até resolver. Atualize o `run.json` (`status: paused_for_human`). Ao receber as respostas, registre como decisões e continue.

## 5. Encerrar

Quando a trilha terminar, garanta que `handoff.json` existe, marque `status: done` e mostre ao usuário um resumo curto: trilha usada, artefatos gerados (caminhos), nº de decisões automáticas e de perguntas que precisaram de humano. **Não** abra PR nem implemente código.
```
> Nota de execução: substitua `<PLUGIN>` pelo diretório do plugin instalado. Em runtime, o Claude resolve o caminho do plugin; ao escrever a skill, mantenha o placeholder textual `<PLUGIN>` e instrua o uso de caminho relativo ao plugin.

- [ ] **Step 2: Validar marketplace (agora passa)**

Run: `node scripts/validate.mjs .`
Expected: `✔ Validação OK` (SKILL.md tem frontmatter `name`+`description`; entrada do marketplace casa com `plugin.json`).

- [ ] **Step 3: Commit**

```bash
git add plugins/sismais-dev/skills/sismais-dev/SKILL.md
git commit -m "feat(sismais-dev): skill orquestradora com router e dispatch de estagios"
```

---

## Task 8: Sub-agente `specifier`

**Files:**
- Create: `plugins/sismais-dev/agents/sismais-dev-specifier.md`

- [ ] **Step 1: Criar o agente**

`plugins/sismais-dev/agents/sismais-dev-specifier.md`:
```markdown
---
name: sismais-dev-specifier
description: Estágio specify da pipeline Sismais Dev. Transforma um pedido em spec.md (problema, histórias/critérios de aceite, escopo e não-escopo, regras de negócio), apoiado nas regras e skills de domínio do projeto-alvo. Despachado pelo orquestrador sismais-dev.
tools: Read, Glob, Grep
---

# Specifier — pedido → spec

Você recebe no prompt: o pedido, o caminho do diretório do run, e o `rulesFile`.

Produza o **conteúdo** de `spec.md` (markdown) com as seções:

1. **Problema** — o que o usuário precisa e por quê (contexto de negócio).
2. **Histórias / critérios de aceite** — em linguagem de produto, verificáveis.
3. **Escopo** e **Não-escopo** — explícitos. Liste o que NÃO muda.
4. **Regras de negócio** relevantes — extraídas/coerentes com o `rulesFile` e as skills de domínio do projeto.

Regras:
- Leia o `rulesFile` e as skills de domínio relevantes antes de escrever. Cite a fonte quando uma regra vier delas.
- NÃO decida arquitetura/implementação (isso é do planner).
- Se faltar informação essencial para definir escopo, liste em "Perguntas em aberto" ao final — o clarifier vai tratá-las.

Saída: devolva SOMENTE o conteúdo markdown do `spec.md`. O orquestrador grava o arquivo.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/sismais-dev/agents/sismais-dev-specifier.md
git commit -m "feat(sismais-dev): agente specifier (pedido -> spec)"
```

---

## Task 9: Sub-agente `clarifier` (Pause-or-Decide)

**Files:**
- Create: `plugins/sismais-dev/agents/sismais-dev-clarifier.md`

- [ ] **Step 1: Criar o agente**

`plugins/sismais-dev/agents/sismais-dev-clarifier.md`:
```markdown
---
name: sismais-dev-clarifier
description: Estágio clarify da pipeline Sismais Dev. Resolve ambiguidades da spec aplicando Pause-or-Decide (score 0–3 sobre rulesFile, docs, código e skills); decide quando há base citando fonte, escala ao humano só o genuinamente ambíguo. Despachado pelo orquestrador sismais-dev.
tools: Read, Glob, Grep
---

# Clarifier — resolve ambiguidades (Pause-or-Decide)

Você recebe: caminho do diretório do run, `spec.md`, e o `rulesFile`.

Para cada ponto ambíguo da spec (incluindo "Perguntas em aberto"):

1. Levante 2–4 opções plausíveis.
2. **Score 0–3** da opção candidata, +1 por fonte que a suporta entre:
   - `rulesFile` (regras do projeto)
   - `docs/` do projeto
   - código existente
   - skills de domínio
3. Regra de decisão:
   - **score ≥ 2** → DECIDE; registre `decision`, `score` e `sources` (citação verificável).
   - **score < 2** → PAUSA; devolve a pergunta com `context` curto (por que não deu para decidir).

Saída (JSON, devolvido ao orquestrador):
```json
{
  "decisions": [
    { "question": "...", "decision": "...", "score": 2, "sources": ["AGENTS.md", "src/..."], "stage": "clarify" }
  ],
  "pendingQuestions": [
    { "question": "...", "context": "...", "stage": "clarify" }
  ]
}
```

Regras:
- NÃO invente suporte: se não está escrito no projeto, não conta como fonte.
- NÃO escolha com score 1 a menos que todas as outras opções violem o `rulesFile`.
- Sem prosa fora do JSON.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/sismais-dev/agents/sismais-dev-clarifier.md
git commit -m "feat(sismais-dev): agente clarifier com Pause-or-Decide"
```

---

## Task 10: Sub-agente `planner`

**Files:**
- Create: `plugins/sismais-dev/agents/sismais-dev-planner.md`

- [ ] **Step 1: Criar o agente**

`plugins/sismais-dev/agents/sismais-dev-planner.md`:
```markdown
---
name: sismais-dev-planner
description: Estágio plan da pipeline Sismais Dev. Deriva a arquitetura/abordagem técnica a partir do que JÁ EXISTE no projeto (arquivos/módulos afetados, modelo de dados, reuso de componentes, migrations, offline), produzindo plan.md. Despachado pelo orquestrador sismais-dev.
tools: Read, Glob, Grep
---

# Planner — spec → plano de arquitetura

Você recebe: caminho do run, `spec.md`, decisões do clarifier, e o `rulesFile`.

Produza o **conteúdo** de `plan.md` com:

1. **Abordagem** — a estratégia técnica, derivada dos padrões existentes do projeto (cite os arquivos/skills que embasaram).
2. **Arquivos afetados** — criar/modificar, com responsabilidade de cada um.
3. **Dados** — mudanças de modelo/migrations, se houver (respeitando o `rulesFile`).
4. **Reuso** — componentes/hooks/utils existentes a reaproveitar (não recriar).
5. **Riscos / cenários** — incluindo offline e multi-tenant quando o projeto exigir.

Regras:
- Derive do existente: leia código e skills de arquitetura antes de propor. Prefira reuso a abstração nova.
- Respeite o `rulesFile`. Toda alteração de algo que já funciona entra como item explícito.
- Se uma decisão de arquitetura não tem base no projeto, devolva como `pendingQuestions` (mesmo schema do clarifier) em vez de inventar.

Saída: o conteúdo markdown do `plan.md`. Se houver pendências de arquitetura, devolva também um bloco JSON `{ "pendingQuestions": [...] }` ao final.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/sismais-dev/agents/sismais-dev-planner.md
git commit -m "feat(sismais-dev): agente planner (spec -> plano de arquitetura)"
```

---

## Task 11: Sub-agente `tasker` (+ handoff.json)

**Files:**
- Create: `plugins/sismais-dev/agents/sismais-dev-tasker.md`

- [ ] **Step 1: Criar o agente**

`plugins/sismais-dev/agents/sismais-dev-tasker.md`:
```markdown
---
name: sismais-dev-tasker
description: Estágio tasks da pipeline Sismais Dev. Transforma o plano (ou, na trilha Leve, o pedido direto) em tasks.md e handoff.json — tarefas ordenadas, com critério de aceite, arquivos-alvo e dependências. Despachado pelo orquestrador sismais-dev.
tools: Read, Glob, Grep
---

# Tasker — plano → tarefas + handoff

Você recebe: caminho do run, `plan.md` (se existir) ou o pedido (trilha Leve), e o `rulesFile`.

Produza DOIS conteúdos:

1. **`tasks.md`** — lista ordenada de tarefas. Cada tarefa: título, arquivos-alvo, critério de aceite, dependências. Granularidade implementável (uma tarefa = um bloco lógico coeso).

2. **`handoff.json`** — manifesto estruturado, EXATAMENTE neste schema:
```json
{
  "version": 1,
  "featureSlug": "<slug do run>",
  "spec": "spec.md",
  "plan": "plan.md",
  "tasks": [
    { "id": "T1", "titulo": "...", "arquivosAlvo": ["src/..."], "criterioDeAceite": "...", "dependeDe": [] }
  ]
}
```
(Na trilha Leve, `spec`/`plan` podem ser omitidos ou apontar só para `tasks.md`.)

Regras:
- `id` sequencial `T1..Tn`. `dependeDe` referencia ids anteriores.
- Critério de aceite verificável por tarefa.
- Não implemente nada — só descreva.

Saída: devolva o `tasks.md` (markdown) e o `handoff.json` (bloco JSON) claramente separados. O orquestrador grava ambos.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/sismais-dev/agents/sismais-dev-tasker.md
git commit -m "feat(sismais-dev): agente tasker (plano -> tarefas + handoff)"
```

---

## Task 12: Comandos (`/sismais-dev*`)

**Files:**
- Create: `plugins/sismais-dev/commands/sismais-dev.md`
- Create: `plugins/sismais-dev/commands/sismais-dev-feature.md`
- Create: `plugins/sismais-dev/commands/sismais-dev-fix.md`
- Create: `plugins/sismais-dev/commands/sismais-dev-brainstorm.md`
- Create: `plugins/sismais-dev/commands/sismais-dev-resume.md`

Formato de slash-command do Claude Code: frontmatter (`description`, `argument-hint`) + corpo (prompt) usando `$ARGUMENTS`. Cada comando aciona a skill `sismais-dev` com a trilha apropriada.

- [ ] **Step 1: Criar `sismais-dev.md` (entrada padrão)**

```markdown
---
description: Pipeline SDD — router decide a trilha (Leve/Padrão/Exploratória).
argument-hint: <pedido em linguagem natural>
---

Use a skill `sismais-dev` para processar este pedido, deixando o **router** decidir a trilha:

$ARGUMENTS
```

- [ ] **Step 2: Criar `sismais-dev-feature.md` (força Padrão)**

```markdown
---
description: Pipeline SDD — força a trilha Padrão (spec → clarify → plano → tarefas).
argument-hint: <ideia da feature>
---

Use a skill `sismais-dev` com a **trilha Padrão forçada** (specifier → clarifier → planner → tasker) para:

$ARGUMENTS
```

- [ ] **Step 3: Criar `sismais-dev-fix.md` (força Leve)**

```markdown
---
description: Pipeline SDD — força a trilha Leve (ideia → tarefas).
argument-hint: <ajuste/correção>
---

Use a skill `sismais-dev` com a **trilha Leve forçada** (só tasker, com mini-plano embutido) para:

$ARGUMENTS
```

- [ ] **Step 4: Criar `sismais-dev-brainstorm.md` (força Exploratória)**

```markdown
---
description: Pipeline SDD — força a trilha Exploratória (brainstorm e depois Padrão).
argument-hint: <ideia vaga>
---

Use a skill `sismais-dev` com a **trilha Exploratória forçada** (brainstorm para fixar o objetivo e depois a trilha Padrão) para:

$ARGUMENTS
```

- [ ] **Step 5: Criar `sismais-dev-resume.md` (retomada)**

```markdown
---
description: Pipeline SDD — retoma um run a partir do run.json.
argument-hint: <feature-slug ou caminho do run.json>
---

Use a skill `sismais-dev` para **retomar** o run indicado: leia o `run.json`, identifique os estágios já concluídos (`stagesCompleted`) e continue do próximo estágio sem refazer os anteriores. Trate `pendingQuestions` primeiro se houver.

Run: $ARGUMENTS
```

- [ ] **Step 6: Validar e commit**

Run: `node scripts/validate.mjs .`
Expected: `✔ Validação OK` (commands não afetam o validador).
```bash
git add plugins/sismais-dev/commands/
git commit -m "feat(sismais-dev): comandos /sismais-dev de entrada e retomada"
```

---

## Task 13: Wiring de teste local + README do plugin

**Files:**
- Create: `plugins/sismais-dev/README.md`

- [ ] **Step 1: README do plugin**

`plugins/sismais-dev/README.md`:
```markdown
# sismais-dev

Pipeline SDD adaptativa: transforma um pedido em `spec.md` + `plan.md` + `tasks.md` + `handoff.json`, com router de trilha (Leve/Padrão/Exploratória) e gate Pause-or-Decide. Para antes de implementar código de feature.

## Comandos
- `/sismais-dev <pedido>` — router decide a trilha.
- `/sismais-dev-feature <ideia>` — força Padrão.
- `/sismais-dev-fix <ajuste>` — força Leve.
- `/sismais-dev-brainstorm <ideia vaga>` — força Exploratória.
- `/sismais-dev-resume <slug>` — retoma um run.

## Config por projeto (opcional)
`.sismais-dev.json` na raiz do projeto-alvo:
```json
{ "artifactsRoot": "docs/sismais-dev", "rulesFile": "AGENTS.md" }
```

## Artefatos
Gravados em `<artifactsRoot>/<feature-slug>/`: `spec.md`, `plan.md`, `tasks.md`, `handoff.json`, `run.json`.
```

- [ ] **Step 2: Configurar marketplace local para teste (manual, não versionado)**

Editar `~/.claude/settings.json` (Windows: `%USERPROFILE%\.claude\settings.json`) acrescentando:
```json
{
  "extraKnownMarketplaces": {
    "sismais-local": {
      "source": { "source": "directory", "path": "D:/Sismais/Fontes/sismais-ai-plugins-workspace/sismais-ai-plugins-private" }
    }
  },
  "enabledPlugins": {
    "sismais-dev@sismais-local": true
  }
}
```
Reabrir o Claude Code e aceitar o prompt de confiança.

- [ ] **Step 3: Commit**

```bash
git add plugins/sismais-dev/README.md
git commit -m "docs(sismais-dev): README do plugin e instrucoes de teste local"
```

---

## Task 14: Smoke test end-to-end no gms-mobile (aceitação)

**Files:** nenhum (validação manual). Roda no repo `gms-mobile` com o plugin habilitado via `sismais-local`.

- [ ] **Step 1: Trilha Leve**

No Claude Code dentro do `gms-mobile`, rode `/sismais-dev-fix "corrige rótulo do botão de salvar no formulário de cliente"`.
Expected: cria `docs/sismais-dev/<slug>/tasks.md` + `handoff.json` + `run.json` (`track: leve`, `status: done`), sem spec/plano. Não implementa código.

- [ ] **Step 2: Trilha Padrão + Pause-or-Decide**

Rode `/sismais-dev-feature "adiciona desconto por item no PDV"`.
Expected: gera `spec.md`, `plan.md`, `tasks.md`, `handoff.json`; o `clarifier`/`planner` decidem com citação de fonte onde há base e **pausam** apenas no genuinamente ambíguo (`status: paused_for_human` enquanto pendente). As decisões em `run.json` citam `AGENTS.md`/skills/código.

- [ ] **Step 3: Router automático**

Rode `/sismais-dev "ajusta o placeholder do campo de busca"` (esperado Leve) e `/sismais-dev "permite venda com múltiplas formas de pagamento"` (esperado Padrão).
Expected: `run.json.track` correto em cada caso, com `trackReason` coerente.

- [ ] **Step 4: Retomada**

Interrompa um run Padrão após o estágio `clarify` e rode `/sismais-dev-resume <slug>`.
Expected: continua de `plan` sem refazer `specify`/`clarify` (lê `stagesCompleted`).

- [ ] **Step 5: Conferir critérios de aceitação do spec**

Verifique os 7 critérios da seção "Critérios de aceitação da v0.1" do spec. Anote evidências (caminhos dos artefatos, trechos do `run.json`).

- [ ] **Step 6: Validar + testes finais + commit do que faltar**

```bash
node scripts/validate.mjs .
node --test plugins/sismais-dev/scripts/run-state.test.mjs
```
Expected: validação OK e 13 testes passando.

---

## Self-Review (preenchido)

**Cobertura do spec:**
- Plugin no padrão marketplace + registro → Task 1. ✓
- Router (Leve/Padrão/Exploratória) + override → Task 7 + Task 12. ✓
- Estágios specifier/clarifier/planner/tasker → Tasks 8–11. ✓
- Pause-or-Decide → Task 9 (clarifier) e Task 10 (planner). ✓
- Comandos `/sismais-dev*` incl. resume → Task 12. ✓
- Artefatos no projeto-alvo + `run.json`/`handoff.json` → schemas no topo; Tasks 4–6 (run.json) e 11 (handoff.json). ✓
- Estado leve + retomada → Tasks 4–6 + Task 14 Step 4. ✓
- Reuso do conhecimento do projeto (rulesFile/skills) → Tasks 7–11 (instruções explícitas). ✓
- Sync de prototipagem → Task 13 Step 2. ✓
- Validador/CI passando, PT user-facing → Tasks 1/7/12 e critérios. ✓
- Fora de escopo (loop, painel, produto inteiro, waves/wakeup, auto-PR) → não há tasks (correto). ✓

**Placeholders:** nenhum "TBD/TODO"; conteúdo completo por arquivo. O `<PLUGIN>` na SKILL.md é placeholder textual intencional (resolvido em runtime), documentado.

**Consistência de tipos/nomes:** funções de `run-state.mjs` (`slugify`, `resolveConfig`, `runDir`, `initRun`, `readRun`, `markStage`, `appendDecision`, `setPending`, `setStatus`, `setArtifacts`) usadas com os mesmos nomes em testes e CLI. Nomes de agentes (`sismais-dev-specifier|clarifier|planner|tasker`) idênticos entre SKILL.md e os arquivos de agente. Schemas (`run.json`, `handoff.json`, `.sismais-dev.json`) idênticos entre topo, scripts e agentes.

## Questões remanescentes (verificar na execução, não bloqueiam)

- Schema exato do frontmatter de `commands/*.md` e `agents/*.md` empacotados em plugin: confirmar contra a doc atual do Claude Code no Step de smoke (Task 14). Default congelado conforme acima.
- Resolução do caminho `<PLUGIN>` dentro da SKILL.md em runtime (variável de ambiente de plugin vs. caminho relativo) — ajustar no primeiro smoke.
