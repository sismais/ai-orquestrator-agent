# Sismais Dev — Loop Autônomo (v1) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o plugin `sismais-dev-loop` que implementa uma tarefa numa branch, revisa (independente), corrige, valida, abre PR, espera o CI e para no ready-to-merge — com humano mínimo, sem nunca fazer merge.

**Architecture:** Skill orquestradora conduz o loop e centraliza git/PR/CI; despacha sub-agentes frescos por etapa (implementer, reviewer independente, ci-triage). Estado durável e testável em `loop-state.mjs` (`loop.json`). Self-contained; conhecimento vem do projeto-alvo (`AGENTS.md` + skills).

**Tech Stack:** Claude Code plugin (markdown: skill/agents/commands) · Node 20+ ESM (`loop-state.mjs`, testes `node --test`) · `gh` CLI (PR/CI) · validador de marketplace existente.

---

## Decisões travadas (resolvem as "questões em aberto" do spec)

- **Branch:** `sismais-dev/<slug>` a partir de `baseBranch`. Nunca `main`.
- **maxIterations:** default `6`; conta **por rodada de review→fix** (e idem no ciclo de CI).
- **Sugestão de merge:** default `squash` (o loop produz vários commits de processo); descrição = resumo da tarefa + principais mudanças.
- **Espera CI:** `gh pr checks <pr> --watch`; por check que falhar, `ci-triage` julga related/unrelated.
- **Caminho de script:** `${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs` (literal, resolvido em runtime — como no sub-projeto 1).
- **Worktree:** `useWorktree` (default false); quando true, cria worktree + `npm ci`/`npm install`; cleanup por comando.
- **Estado:** `loop-state.mjs` próprio (self-contained; não reusa `run-state.mjs`).
- **Lições do review anterior bakeadas:** `parseArgs` rejeita flag sem valor; `initLoop` guarda contra clobber.

## Mapa de arquivos (repo `sismais-ai-plugins-private`)

```
plugins/sismais-dev-loop/
├── .claude-plugin/plugin.json
├── skills/sismais-dev-loop/SKILL.md          # orquestrador do loop
├── agents/
│   ├── sismais-dev-implementer.md
│   ├── sismais-dev-reviewer.md
│   └── sismais-dev-ci-triage.md
├── commands/
│   ├── sismais-dev-build.md
│   ├── sismais-dev-build-resume.md
│   └── sismais-dev-build-cleanup.md
├── scripts/
│   ├── loop-state.mjs
│   └── loop-state.test.mjs
└── README.md
```
- Modificar: `.claude-plugin/marketplace.json` (entrada `sismais-dev-loop`).

`loop-state.mjs` concentra a lógica determinística/testável. Os `.md` são prompts. O validador só inspeciona `skills/*/SKILL.md`.

## Schema `loop.json` (referência)

```json
{
  "version": 1,
  "task": "<tarefa>",
  "taskSlug": "<slug>",
  "branch": "sismais-dev/<slug>",
  "baseBranch": "main",
  "worktreePath": null,
  "iterations": [],
  "ci": { "status": "pending", "checks": [] },
  "prUrl": null,
  "status": "in_progress",
  "pause": null,
  "mergeSuggestion": null
}
```
- `iterations[]`: `{ "n", "stage", "findings": {"blocks","fixNow","suggestions"}, "action" }`
- `ci.status`: `pending|green|red|unrelated`
- `status`: `in_progress|paused_for_human|ready_to_merge`
- `pause`: `{ "reason", "context" }` · `mergeSuggestion`: `{ "type": "squash|merge", "description" }`

---

## Task 1: Scaffold do plugin + registro no marketplace

**Files:**
- Create: `plugins/sismais-dev-loop/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Criar `plugin.json`**

`plugins/sismais-dev-loop/.claude-plugin/plugin.json`:
```json
{
  "name": "sismais-dev-loop",
  "version": "0.1.0",
  "description": "Loop autônomo de implementação/review — implementa uma tarefa, revisa, corrige, abre PR, espera CI e para no ready-to-merge.",
  "author": { "name": "Sismais" }
}
```

- [ ] **Step 2: Registrar no `marketplace.json`** (adicionar ao array `plugins[]`, após a última entrada)

```json
{
  "name": "sismais-dev-loop",
  "source": "./plugins/sismais-dev-loop",
  "description": "Loop autônomo: implementa uma tarefa, revisa (independente), corrige, abre PR, espera CI e para no ready-to-merge.",
  "version": "0.1.0",
  "category": "workflow",
  "tags": ["loop", "review", "autonomous", "internal"]
}
```

- [ ] **Step 3: Criar diretórios**

Run:
```bash
mkdir -p plugins/sismais-dev-loop/skills/sismais-dev-loop plugins/sismais-dev-loop/agents plugins/sismais-dev-loop/commands plugins/sismais-dev-loop/scripts
```

- [ ] **Step 4: Validar**

Run: `node scripts/validate.mjs .`
Expected: `✔ Validação OK` (o validador pula SKILL.md ausente; confirme JSON válido e 3-way match de `sismais-dev-loop`).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev-loop/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat(sismais-dev-loop): scaffold do plugin e registro no marketplace"
```

---

## Task 2: `loop-state.mjs` + testes (TDD, módulo completo)

**Files:**
- Create: `plugins/sismais-dev-loop/scripts/loop-state.test.mjs`
- Create: `plugins/sismais-dev-loop/scripts/loop-state.mjs`

- [ ] **Step 1: Escrever os testes (completo)**

`plugins/sismais-dev-loop/scripts/loop-state.test.mjs`:
```js
import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  slugify, resolveConfig, loopDir, initLoop, readLoop,
  recordIteration, setCI, setPR, setStatus, setPause, setMergeSuggestion
} from './loop-state.mjs';

const CLI = fileURLToPath(new URL('./loop-state.mjs', import.meta.url));
function tmpRepo() { return fs.mkdtempSync(path.join(os.tmpdir(), 'sismais-loop-')); }
function freshLoop() {
  const repo = tmpRepo();
  return initLoop(repo, { task: 'Tarefa X', branch: 'sismais-dev/tarefa-x', baseBranch: 'main' });
}

test('slugify gera kebab-case ascii sem acentos', () => {
  assert.equal(slugify('Botão de Emissão'), 'botao-de-emissao');
});

test('resolveConfig traz defaults do loop quando nao ha arquivo', () => {
  const repo = tmpRepo();
  assert.deepEqual(resolveConfig(repo), {
    artifactsRoot: 'docs/sismais-dev', rulesFile: 'AGENTS.md',
    validateCommand: 'npm run lint && npx tsc --noEmit && npm test',
    baseBranch: 'main', maxIterations: 6, reviewCommand: null, useWorktree: false
  });
});

test('resolveConfig mescla overrides', () => {
  const repo = tmpRepo();
  fs.writeFileSync(path.join(repo, '.sismais-dev.json'), JSON.stringify({ maxIterations: 3, useWorktree: true }));
  const c = resolveConfig(repo);
  assert.equal(c.maxIterations, 3);
  assert.equal(c.useWorktree, true);
  assert.equal(c.baseBranch, 'main');
});

test('loopDir respeita artifactsRoot', () => {
  const repo = tmpRepo();
  assert.equal(loopDir(repo, 'x'), path.join(repo, 'docs/sismais-dev', 'x'));
});

test('initLoop grava loop.json com status in_progress e ci pending', () => {
  const loopPath = freshLoop();
  const loop = readLoop(loopPath);
  assert.equal(loop.version, 1);
  assert.equal(loop.status, 'in_progress');
  assert.deepEqual(loop.ci, { status: 'pending', checks: [] });
  assert.equal(loop.taskSlug, 'tarefa-x');
  assert.equal(loop.prUrl, null);
});

test('initLoop lanca erro se o loop ja existe (anti-clobber)', () => {
  const repo = tmpRepo();
  initLoop(repo, { task: 'dup', branch: 'b', baseBranch: 'main', taskSlug: 'dup' });
  assert.throws(() => initLoop(repo, { task: 'dup', branch: 'b', baseBranch: 'main', taskSlug: 'dup' }), /existe/);
});

test('recordIteration acrescenta', () => {
  const loopPath = freshLoop();
  recordIteration(loopPath, { n: 1, stage: 'review', findings: { blocks: 0, fixNow: 2, suggestions: 1 }, action: 'fixed' });
  assert.equal(readLoop(loopPath).iterations.length, 1);
});

test('setCI / setPR / setStatus', () => {
  const loopPath = freshLoop();
  setCI(loopPath, { status: 'green', checks: ['build'] });
  setPR(loopPath, 'https://github.com/x/y/pull/1');
  setStatus(loopPath, 'in_progress');
  const loop = readLoop(loopPath);
  assert.equal(loop.ci.status, 'green');
  assert.equal(loop.prUrl, 'https://github.com/x/y/pull/1');
});

test('setPause marca paused_for_human; limpar nao rebaixa', () => {
  const loopPath = freshLoop();
  setPause(loopPath, { reason: 'ambiguo', context: 'c' });
  assert.equal(readLoop(loopPath).status, 'paused_for_human');
  setStatus(loopPath, 'ready_to_merge');
  setPause(loopPath, null);
  assert.equal(readLoop(loopPath).status, 'ready_to_merge');
});

test('setMergeSuggestion marca ready_to_merge', () => {
  const loopPath = freshLoop();
  setMergeSuggestion(loopPath, { type: 'squash', description: 'resumo' });
  const loop = readLoop(loopPath);
  assert.equal(loop.status, 'ready_to_merge');
  assert.equal(loop.mergeSuggestion.type, 'squash');
});

test('CLI init imprime o caminho e grava in_progress', () => {
  const repo = tmpRepo();
  const out = execFileSync('node', [CLI, 'init', '--repo', repo, '--task', 'Teste CLI', '--branch', 'sismais-dev/teste-cli', '--base', 'main'], { encoding: 'utf8' }).trim();
  assert.ok(out.endsWith('loop.json'));
  assert.equal(readLoop(out).taskSlug, 'teste-cli');
});

test('CLI rejeita flag sem valor', () => {
  const loopPath = freshLoop();
  assert.throws(
    () => execFileSync('node', [CLI, 'set-pr', '--loop', loopPath, '--url'], { encoding: 'utf8', stdio: 'pipe' }),
    /./
  );
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test plugins/sismais-dev-loop/scripts/loop-state.test.mjs`
Expected: FAIL — `Cannot find module './loop-state.mjs'`.

- [ ] **Step 3: Escrever o módulo (completo)**

`plugins/sismais-dev-loop/scripts/loop-state.mjs`:
```js
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function slugify(text) {
  return String(text)
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

const DEFAULT_CONFIG = {
  artifactsRoot: 'docs/sismais-dev',
  rulesFile: 'AGENTS.md',
  validateCommand: 'npm run lint && npx tsc --noEmit && npm test',
  baseBranch: 'main',
  maxIterations: 6,
  reviewCommand: null,
  useWorktree: false
};

export function resolveConfig(repoRoot) {
  const cfgPath = path.join(repoRoot, '.sismais-dev.json');
  if (!fs.existsSync(cfgPath)) return { ...DEFAULT_CONFIG };
  const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  return { ...DEFAULT_CONFIG, ...raw };
}

export function loopDir(repoRoot, slug) {
  const { artifactsRoot } = resolveConfig(repoRoot);
  return path.join(repoRoot, artifactsRoot, slug);
}

function writeLoop(loopPath, loop) {
  fs.writeFileSync(loopPath, JSON.stringify(loop, null, 2) + '\n');
}

export function readLoop(loopPath) {
  return JSON.parse(fs.readFileSync(loopPath, 'utf8'));
}

export function initLoop(repoRoot, { task, branch, baseBranch, worktreePath = null, taskSlug }, { overwrite = false } = {}) {
  const slug = taskSlug || slugify(task);
  const dir = loopDir(repoRoot, slug);
  const loopPath = path.join(dir, 'loop.json');
  if (!overwrite && fs.existsSync(loopPath)) throw new Error(`Loop já existe: ${loopPath}`);
  fs.mkdirSync(dir, { recursive: true });
  const loop = {
    version: 1, task, taskSlug: slug, branch, baseBranch, worktreePath,
    iterations: [], ci: { status: 'pending', checks: [] },
    prUrl: null, status: 'in_progress', pause: null, mergeSuggestion: null
  };
  writeLoop(loopPath, loop);
  return loopPath;
}

export function recordIteration(loopPath, iteration) {
  const loop = readLoop(loopPath);
  loop.iterations.push(iteration);
  writeLoop(loopPath, loop);
  return loop;
}

export function setCI(loopPath, ci) {
  const loop = readLoop(loopPath);
  loop.ci = ci;
  writeLoop(loopPath, loop);
  return loop;
}

export function setPR(loopPath, url) {
  const loop = readLoop(loopPath);
  loop.prUrl = url;
  writeLoop(loopPath, loop);
  return loop;
}

export function setStatus(loopPath, status) {
  const loop = readLoop(loopPath);
  loop.status = status;
  writeLoop(loopPath, loop);
  return loop;
}

export function setPause(loopPath, pause) {
  const loop = readLoop(loopPath);
  loop.pause = pause;
  if (pause) loop.status = 'paused_for_human';
  writeLoop(loopPath, loop);
  return loop;
}

export function setMergeSuggestion(loopPath, suggestion) {
  const loop = readLoop(loopPath);
  loop.mergeSuggestion = suggestion;
  loop.status = 'ready_to_merge';
  writeLoop(loopPath, loop);
  return loop;
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    const val = argv[i + 1];
    if (val === undefined || val.startsWith('--')) throw new Error(`Argumento sem valor: --${key}`);
    args[key] = val;
  }
  return args;
}

function isMain() {
  return fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || '');
}

if (isMain()) {
  const [cmd, ...rest] = process.argv.slice(2);
  const a = parseArgs(rest);
  if (cmd === 'init') {
    const loopPath = initLoop(a.repo, { task: a.task, branch: a.branch, baseBranch: a.base, worktreePath: a.worktree || null, taskSlug: a.slug });
    process.stdout.write(loopPath + '\n');
  } else if (cmd === 'record-iteration') {
    recordIteration(a.loop, JSON.parse(a.json)); process.stdout.write('ok\n');
  } else if (cmd === 'set-ci') {
    setCI(a.loop, JSON.parse(a.json)); process.stdout.write('ok\n');
  } else if (cmd === 'set-pr') {
    setPR(a.loop, a.url); process.stdout.write('ok\n');
  } else if (cmd === 'set-status') {
    setStatus(a.loop, a.status); process.stdout.write('ok\n');
  } else if (cmd === 'set-pause') {
    setPause(a.loop, JSON.parse(a.json)); process.stdout.write('ok\n');
  } else if (cmd === 'set-merge') {
    setMergeSuggestion(a.loop, JSON.parse(a.json)); process.stdout.write('ok\n');
  } else if (cmd === 'dir') {
    process.stdout.write(loopDir(a.repo, a.slug) + '\n');
  } else {
    process.stderr.write(`comando desconhecido: ${cmd}\n`); process.exit(1);
  }
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node --test plugins/sismais-dev-loop/scripts/loop-state.test.mjs`
Expected: PASS (12 testes).

- [ ] **Step 5: Commit**

```bash
git add plugins/sismais-dev-loop/scripts/loop-state.mjs plugins/sismais-dev-loop/scripts/loop-state.test.mjs
git commit -m "feat(sismais-dev-loop): loop-state.mjs (estado do loop, CLI) + testes"
```

---

## Task 3: Skill orquestradora `sismais-dev-loop`

**Files:**
- Create: `plugins/sismais-dev-loop/skills/sismais-dev-loop/SKILL.md`

- [ ] **Step 1: Criar a SKILL.md**

`plugins/sismais-dev-loop/skills/sismais-dev-loop/SKILL.md`:
```markdown
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
- Init: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" init --repo "<raiz>" --task "<tarefa>" --branch "<branch>" --base "<baseBranch>"`. Guarde o `loopPath` impresso.

## 1. Implementa
Despache `sismais-dev-implementer` (Task tool) com a tarefa + `rulesFile` + contexto. Ele edita código+testes e reporta. Você faz o commit na branch.

## 2. Revisa (independente)
Despache `sismais-dev-reviewer` (sub-agente FRESCO) com o diff + `rulesFile` → achados em baldes (`blocks`/`fixNow`/`suggestions`). Se `reviewCommand` estiver setado, rode-o em vez disso.
Registre: `... record-iteration --loop "<loopPath>" --json '{"n":N,"stage":"review","findings":{"blocks":B,"fixNow":F,"suggestions":S},"action":"<...>"}'`.

## 3. Corrige (loop)
Se `blocks` ou `fixNow` > 0: despache o implementer para corrigir SÓ esses achados → commit → volte ao passo 2.
Pare o loop quando: revisor sem `blocks`/`fixNow`, **ou** nº de iterações == `maxIterations` → **PAUSE** ("não convergiu").

## 4. Valida local
Rode o `validateCommand`. Falhou → implementer corrige → commit → revalide (e re-revise se mudou código).

## 5. PR
Push da branch. `gh pr create --draft --base "<baseBranch>" --title "<título>" --body "<descrição gerada>"`. Promova: `gh pr ready <pr>`. Registre: `... set-pr --loop "<loopPath>" --url "<url>"`.

## 6. Espera CI
`gh pr checks <pr> --watch`. Para cada check que falhar, despache `sismais-dev-ci-triage` com o log da falha + o diff:
- `related` → implementer corrige → commit → push → re-espere.
- `unrelated`/flaky → registre em `ci` e **não persiga**.
Registre: `... set-ci --loop "<loopPath>" --json '{"status":"green|red|unrelated","checks":[...]}'`.

## 7. Para (ready-to-merge)
Com review limpo + local verde + CI verde: gere a sugestão de merge (default `squash`; descrição = resumo da tarefa + principais mudanças):
`... set-merge --loop "<loopPath>" --json '{"type":"squash","description":"<...>"}'` (marca `ready_to_merge`).
Reporte ao usuário: resumo, URL do PR, sugestão de merge + descrição. **Pare. Não faça merge.**

## Pause-or-Decide
Pause (`... set-pause --loop "<loopPath>" --json '{"reason":"<...>","context":"<...>"}'`) **só** quando: tarefa ambígua sem base no projeto; achado que exige decisão de produto/arquitetura; ação destrutiva/arriscada (migration/RLS/prod/edge function, conforme `rulesFile`); conflito de merge inseguro; ou não-convergência (teto). Apresente a decisão ao usuário e pare.

## Modo retomada
`/sismais-dev-build-resume <slug>`: ache o run com `... dir --repo "<raiz>" --slug "<slug>"`, leia o `loop.json` e continue do ponto (status/iterations/ci) sem refazer o concluído.

## Guardrails
Branch de feature sempre; nunca `main`; nunca merge. Respeite os hooks do projeto (`guard-direct-push` — `gh pr ready` não é push; `guard-supabase-writes`). Só persiga falha de CI `related`.
```

- [ ] **Step 2: Validar e commit**

Run: `node scripts/validate.mjs .` → `✔ Validação OK`.
```bash
git add plugins/sismais-dev-loop/skills/sismais-dev-loop/SKILL.md
git commit -m "feat(sismais-dev-loop): skill orquestradora do loop"
```

---

## Task 4: Sub-agentes (implementer, reviewer, ci-triage)

**Files:**
- Create: `plugins/sismais-dev-loop/agents/sismais-dev-implementer.md`
- Create: `plugins/sismais-dev-loop/agents/sismais-dev-reviewer.md`
- Create: `plugins/sismais-dev-loop/agents/sismais-dev-ci-triage.md`

- [ ] **Step 1: `sismais-dev-implementer.md`**
```markdown
---
name: sismais-dev-implementer
description: Estágio de implementação/correção do loop Sismais Dev. Implementa uma tarefa, ou corrige achados de review / falhas de CI, editando código + testes no projeto-alvo seguindo as regras e padrões do projeto. Despachado pelo orquestrador sismais-dev-loop.
tools: Read, Glob, Grep, Edit, Write, Bash
---

# Implementer — implementa/corrige

Você recebe: a tarefa (ou a lista de achados/falhas a corrigir), o `rulesFile`, e o contexto.

- Leia o `rulesFile` + skills/código relevantes ANTES de editar. Siga padrões existentes; prefira reuso a abstração nova.
- Implemente a tarefa OU corrija EXATAMENTE os achados/falhas passados — nada além (YAGNI).
- Escreva/atualize testes quando o projeto testa aquele tipo de código.
- **NÃO** faça commit, push, PR ou merge — isso é do orquestrador. **NÃO** troque de branch.
- Se a tarefa for ambígua, exigir decisão de produto/arquitetura, ou for destrutiva/arriscada (migration/RLS/prod), **não decida sozinho**: reporte `status: needs_human` com o contexto.

Reporte: arquivos mudados, o que testou, e `status`: `done` | `needs_human` (com motivo/contexto).
```

- [ ] **Step 2: `sismais-dev-reviewer.md`**
```markdown
---
name: sismais-dev-reviewer
description: Revisor independente do loop Sismais Dev. Avalia o diff contra as regras e padrões do projeto-alvo (rulesFile + skills + código) e devolve achados em baldes (bloqueia merge / corrige agora / sugestão), com citação de fonte. Independente do implementador. Despachado pelo orquestrador sismais-dev-loop.
tools: Read, Glob, Grep, Bash
---

# Reviewer — review independente (grounding)

Você é o "segundo dev". Recebe: o diff (ou a branch), e o `rulesFile`. **Não confie em nenhum relato do implementador** — leia o código real.

Avalie contra: o `rulesFile`, as skills/docs de domínio e o código existente. Procure: bugs, lógica errada, violação de regra de negócio/convenção, falha silenciosa, problema de segurança/multi-tenant, teste ausente em regra crítica.

Saída (JSON, sem prosa fora dele):
```json
{
  "blocks": [ { "titulo": "...", "arquivo": "src/..:linha", "porque": "...", "fonte": "AGENTS.md|skill|codigo" } ],
  "fixNow": [ { "titulo": "...", "arquivo": "...", "porque": "...", "fonte": "..." } ],
  "suggestions": [ { "titulo": "...", "porque": "..." } ]
}
```
- `blocks` = impede merge; `fixNow` = corrige antes de fechar; `suggestions` = opcional.
- Cite fonte verificável. Só reporte com confiança alta.
```

- [ ] **Step 3: `sismais-dev-ci-triage.md`**
```markdown
---
name: sismais-dev-ci-triage
description: Triagem de falha de CI no loop Sismais Dev. Dado o log de um check de CI que falhou e o diff do PR, julga se a falha é causada pelo diff (related) ou é pré-existente/flaky/infra (unrelated). Despachado pelo orquestrador sismais-dev-loop.
tools: Read, Glob, Grep, Bash
---

# CI Triage — relacionado ao diff?

Você recebe: o log/resumo do check de CI que falhou e o diff do PR. Julgue se a falha é **causada pelo diff**.

Critério: a falha toca arquivos/símbolos do diff, ou é consequência lógica das mudanças → `related`. Falha em área não tocada, erro de infra/rede, ou teste reconhecidamente flaky → `unrelated`.

Saída (JSON, sem prosa fora dele): `{ "verdict": "related" | "unrelated", "porque": "<1-2 frases citando o que no log/diff embasou>" }`.
```

- [ ] **Step 4: Validar e commit**

Run: `node scripts/validate.mjs .` → `✔ Validação OK`.
```bash
git add plugins/sismais-dev-loop/agents/
git commit -m "feat(sismais-dev-loop): sub-agentes implementer, reviewer e ci-triage"
```

---

## Task 5: Comandos

**Files:**
- Create: `plugins/sismais-dev-loop/commands/sismais-dev-build.md`
- Create: `plugins/sismais-dev-loop/commands/sismais-dev-build-resume.md`
- Create: `plugins/sismais-dev-loop/commands/sismais-dev-build-cleanup.md`

- [ ] **Step 1: `sismais-dev-build.md`**
```markdown
---
description: Loop autônomo — implementa uma tarefa até ready-to-merge (review + PR + CI), parando só no que exige humano.
argument-hint: <tarefa em linguagem natural>
---

Use a skill `sismais-dev-loop` para implementar de forma autônoma a tarefa abaixo: branch → implementa → revisa (independente) → corrige → valida → PR draft → ready → espera CI → para no ready-to-merge. Não faça merge.

$ARGUMENTS
```

- [ ] **Step 2: `sismais-dev-build-resume.md`**
```markdown
---
description: Loop autônomo — retoma um run a partir do loop.json.
argument-hint: <task-slug>
---

Use a skill `sismais-dev-loop` em **modo retomada**: leia o `loop.json` do slug indicado, identifique o ponto (status, iterations, ci) e continue de onde parou, sem refazer o concluído. Trate `pause` primeiro se houver.

Slug: $ARGUMENTS
```

- [ ] **Step 3: `sismais-dev-build-cleanup.md`**
```markdown
---
description: Loop autônomo — remove a worktree e a branch local de um run após o merge.
argument-hint: <task-slug>
---

Use a skill `sismais-dev-loop` para **limpar** o run do slug indicado, com cuidado:
1. Ache o diretório do run: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" dir --repo "<raiz>" --slug "$ARGUMENTS"` e leia o `loop.json` (`branch`, `worktreePath`).
2. Se `worktreePath` estiver setado, rode `git worktree remove "<worktreePath>"` (alerte se houver mudanças não commitadas).
3. Remova a branch local: `git branch -d "<branch>"`. Se o git recusar por não estar mergeada, **pergunte ao usuário** antes de usar `-D`.

Slug: $ARGUMENTS
```

- [ ] **Step 4: Validar e commit**

Run: `node scripts/validate.mjs .` → `✔ Validação OK`.
```bash
git add plugins/sismais-dev-loop/commands/
git commit -m "feat(sismais-dev-loop): comandos build, resume e cleanup"
```

---

## Task 6: README do plugin

**Files:**
- Create: `plugins/sismais-dev-loop/README.md`

- [ ] **Step 1: Criar README**
```markdown
# sismais-dev-loop

Loop autônomo de implementação/review: implementa uma tarefa numa branch, revisa (independente), corrige, valida, abre PR, espera o CI e **para no ready-to-merge**. Humano só aprova e faz o merge — o loop nunca faz merge.

## Comandos
- `/sismais-dev-build <tarefa>` — roda o loop completo.
- `/sismais-dev-build-resume <slug>` — retoma um run.
- `/sismais-dev-build-cleanup <slug>` — remove worktree + branch local após o merge.

## Config por projeto (opcional) — `.sismais-dev.json`
` ` `json
{
  "validateCommand": "npm run lint && npx tsc --noEmit && npm test",
  "baseBranch": "main",
  "maxIterations": 6,
  "reviewCommand": null,
  "useWorktree": false
}
` ` `

## Estado
Cada run grava `<artifactsRoot>/<task-slug>/loop.json` (iterações, ci, prUrl, status, pause, sugestão de merge).

## Guardrails
Branch de feature sempre (nunca main); nunca faz merge; respeita os hooks do projeto; teto de iterações; só persegue falhas de CI relacionadas ao diff.
```
(Render o bloco `.sismais-dev.json` como ```json real.)

- [ ] **Step 2: Validar e commit**

Run: `node scripts/validate.mjs .` → `✔ Validação OK`.
```bash
git add plugins/sismais-dev-loop/README.md
git commit -m "docs(sismais-dev-loop): README do plugin"
```

---

## Task 7: Smoke e2e (manual — handoff ao usuário)

**Files:** nenhum. Requer `gh` autenticado, reload do Claude Code com o plugin habilitado, e um PR/CI reais. Roda no `gms-mobile`.

- [ ] **Step 1: Habilitar o plugin** — adicionar `sismais-dev-loop@sismais-local` em `enabledPlugins` (o marketplace `sismais-local` já aponta para o repo privado). Reabrir o Claude Code.
- [ ] **Step 2: Tarefa clara (não deve pausar)** — `/sismais-dev-build "<ajuste pequeno e claro>"`. Esperado: branch `sismais-dev/<slug>`, commits, PR draft→ready, CI verde, status `ready_to_merge` com sugestão de merge. Sem tocar `main`, sem merge.
- [ ] **Step 3: Tarefa ambígua (deve pausar)** — `/sismais-dev-build "<algo subespecificado>"`. Esperado: pausa com `status: paused_for_human` e contexto da decisão.
- [ ] **Step 4: CI quebrado relacionado** — introduzir (de propósito) algo que quebre o CI e ver o loop corrigir; e um quebrado não-relacionado e ver o loop registrar/ignorar (`ci.status: unrelated`).
- [ ] **Step 5: Worktree** — com `.sismais-dev.json` `useWorktree: true`, conferir que roda na worktree e que `/sismais-dev-build-cleanup <slug>` a remove.
- [ ] **Step 6: Conferir** os critérios de aceitação do spec e anotar evidências.

---

## Self-Review (preenchido)

**Cobertura do spec:**
- Plugin + registro → Task 1. ✓
- Loop completo (setup→implementa→revisa→corrige→valida→PR→ready→espera CI→para) → Task 3 (SKILL.md). ✓
- Revisor independente + grounding → Task 4 (reviewer). ✓
- Implementer + ci-triage → Task 4. ✓
- Pause-or-Decide → Task 3 (seção) + implementer `needs_human` (Task 4). ✓
- Worktree opt-in + cleanup → Task 3 (setup) + Task 5 (cleanup). ✓
- Estado `loop.json` + CLI → Task 2. ✓
- Sugestão de merge → Task 2 (`setMergeSuggestion`) + Task 3 (passo 7). ✓
- Guardrails → Task 3 (seção). ✓
- Config estendida → Task 2 (`DEFAULT_CONFIG`). ✓
- Comandos build/resume/cleanup → Task 5. ✓
- Critérios de aceitação → Task 7 (smoke). ✓
- Fora de escopo (notificação, auto-merge, handoff.json, Stop-hook, auto-destroy worktree, loops paralelos) → sem tasks. ✓

**Placeholders:** sem TBD/TODO. O `${CLAUDE_PLUGIN_ROOT}` é literal intencional (runtime). O `` ` ` ` `` no README é instrução de render (vira ```json real).

**Consistência de nomes/schemas:** funções de `loop-state.mjs` (`slugify`, `resolveConfig`, `loopDir`, `initLoop`, `readLoop`, `recordIteration`, `setCI`, `setPR`, `setStatus`, `setPause`, `setMergeSuggestion`) idênticas entre módulo, testes e CLI. Comandos CLI (`init`, `record-iteration`, `set-ci`, `set-pr`, `set-status`, `set-pause`, `set-merge`, `dir`) referenciados consistentemente na SKILL.md. Nomes de agentes (`sismais-dev-implementer`/`-reviewer`/`-ci-triage`) idênticos entre SKILL.md e arquivos. Schema `loop.json` idêntico entre topo, `loop-state.mjs` e SKILL.md.

## Questões remanescentes (verificar na execução)

- Sintaxe/saída exata de `gh pr checks --watch` em git-bash no Windows; fallback de polling se `--watch` não estiver disponível.
- `npm ci` vs `npm install` na worktree conforme exista `package-lock.json`.
- Heurística fina da descrição de squash (o que entra no corpo).
