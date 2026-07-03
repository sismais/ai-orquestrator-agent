---
description: Loop autônomo — remove a worktree e a branch local de um run após o merge.
argument-hint: <task-slug>
---

Use a skill `sismais-dev-loop` para **limpar** o run do slug indicado, com cuidado:
1. Ache o diretório do run: `node "${CLAUDE_PLUGIN_ROOT}/scripts/loop-state.mjs" dir --repo "<raiz>" --slug "$ARGUMENTS"` e leia o `loop.json` (`branch`, `worktreePath`).
2. Se `worktreePath` estiver setado, rode `git worktree remove "<worktreePath>"` (alerte se houver mudanças não commitadas).
3. Remova a branch local: `git branch -d "<branch>"`. Se o git recusar por não estar mergeada, **pergunte ao usuário** antes de usar `-D`.

Slug: $ARGUMENTS
