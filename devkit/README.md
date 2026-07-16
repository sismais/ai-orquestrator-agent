# devkit/ — camada de agentes do DevKit

Skills, comandos e subagentes do **Sismais AI DevKit**. O **orquestrador (backend) os carrega
localmente via `claude-agent-sdk`** por run, apontando o `cwd` para a worktree do projeto-alvo.

> **Fonte única (2026-07-16):** os `agents/*.md` e `schemas/` são **cópias sincronizadas** do
> `devkit-core/` do repo `sismais-ai-plugins-private` — **não edite aqui**; edite lá e rode
> `node devkit-core/sync.mjs --platform <este repo>`. O sync grava
> `devkit-core.manifest.json` e o teste `backend/tests/test_devkit_core_contract.py` falha
> se as cópias divergirem do manifest (anti-drift). Design:
> `docs/specs/2026-07-16-devkit-core-e-entrega-rapida-design.md`.

## O que tem aqui (`.claude/`)

- `commands/` — comandos `/sismais-dev-*` (pontos de entrada que o SDK invoca como prompt).
- `agents/` — subagentes de etapa: `specifier`, `clarifier`, `planner`, `tasker` (pipeline);
  `implementer`, `reviewer`, `ci-triage` (loop).
- `skills/` — `sismais-dev` (pipeline SDD) e `sismais-dev-loop` (loop até o PR).

## O que **não** migrou (e por quê)

- **Scripts de estado** (`scripts/run-state.mjs`, `loop-state.mjs`): a orquestração e o estado
  saem do skill e passam para o **backend** (tabelas `Card`/`Execution`), conforme o design
  (`docs/specs/2026-06-17-ai-orquestrador-panel-design.md`). Por isso as chamadas
  `node "${CLAUDE_PLUGIN_ROOT}/scripts/*.mjs"` que ainda aparecem nos `SKILL.md` ficam **inertes**
  sob o SDK (`${CLAUDE_PLUGIN_ROOT}` nem é definido fora do marketplace) — o **runner do backend
  as substitui na Fase 3**. O `sismais-dev-loop/SKILL.md` serve, até lá, como referência da
  lógica de orquestração a ser portada (fix-loop, guardrails, CI, Pause-or-Decide).

## Origem / crédito

Migrado de `sismais/sismais-ai-plugins-private` (plugins `sismais-dev` e `sismais-dev-loop`).
Histórico de design e planos em `docs/{specs,plans}/`.
