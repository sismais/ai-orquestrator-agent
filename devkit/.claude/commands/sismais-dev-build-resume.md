---
description: Loop autônomo — retoma um run a partir do loop.json.
argument-hint: <task-slug>
---

Use a skill `sismais-dev-loop` em **modo retomada**: leia o `loop.json` do slug indicado, identifique o ponto (status, iterations, ci) e continue de onde parou, sem refazer o concluído. **Se `status === 'paused_for_human'`**, apresente `pause.reason` + `pause.context` ao usuário, aguarde a resposta, e então rode `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" set-status --loop "<loopPath>" --status in_progress` antes de continuar.

Slug: $ARGUMENTS
