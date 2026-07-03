# Spike — carregamento de skill/comando do DevKit no SDK dentro de worktree

**Data:** 2026-06-17 · **Fase 1, Task 3 (de-risk)** · **Resultado: ✅ CONFIRMADO**

## Pergunta

O `claude-agent-sdk` (Python) reconhece nossas skills/comandos do DevKit quando o `cwd`
é uma **git worktree** — onde `.git` é *arquivo*, não pasta (a borda que quebrou o caminho
Gemini do autor do fork)?

## Montagem

- Worktree criada de `gms-mobile`: `git worktree add _spike-wt -b spike-skill-loading`.
  Confirmado que `_spike-wt/.git` é **arquivo** ASCII (62 bytes), não diretório.
- `devkit/.claude` copiado para dentro da worktree (`_spike-wt/.claude/`).
- `spike/skill_loading_spike.py` com:
  ```python
  ClaudeAgentOptions(
      cwd=worktree,
      setting_sources=["project"],   # le .claude/ da worktree
      allowed_tools=["Skill", "Read", "Glob", "Grep"],
      permission_mode="acceptEdits",
  )
  prompt = "/sismais-dev-fix spike: confirme em uma linha..."
  ```
- **Sem `ANTHROPIC_API_KEY`** no ambiente.

## Resultado

1. **Discovery:** a `SystemMessage` de init listou **todos** os nossos slash commands —
   `sismais-dev`, `sismais-dev-loop`, `sismais-dev-brainstorm`, `sismais-dev-build`,
   `sismais-dev-build-cleanup`, `sismais-dev-build-resume`, `sismais-dev-feature`,
   `sismais-dev-fix`, `sismais-dev-resume`.
2. **Execução:** `/sismais-dev-fix` acionou a skill `sismais-dev` (trilha Leve) e respondeu
   confirmando o carregamento, sem editar arquivos.
3. **Auth:** rodou sem API key → usou o login do Claude Code CLI (**assinatura Max**).
4. A borda `.git`-arquivo **não** afetou o carregamento (era limitação do Gemini CLI, não do SDK Claude).

## Decisão para o backend (Fase 3)

- **Mecanismo escolhido:** *worktree-copy* — o runner copia `devkit/.claude` para dentro da
  worktree do card na criação, e invoca o SDK com `cwd=<worktree>`,
  `setting_sources=["project"]`, `allowed_tools` incluindo `"Skill"`. Mantém **global e
  repo-alvo limpos** (a worktree é descartável).
- **Auth:** default = assinatura Max do CLI (sem key). `ANTHROPIC_API_KEY` opcional para
  forçar a API (CI/carga pesada, onde os termos pedem key).
- **Alternativas não escolhidas (registradas):**
  - *user-scope* (`~/.claude` + `setting_sources=["user"]`) — funciona, mas **suja o global**.
  - *local plugin* (`plugins=[{"type":"local","path":...}]`, SDK 0.2.110) — mais elegante
    (sem cópia por-run), mas exige reempacotar `devkit/` como plugin (`.claude-plugin/plugin.json`).
    **Candidato a otimização futura** se a cópia por-run incomodar.

## Observações

- SDK: `claude-agent-sdk==0.2.110`. Fields úteis descobertos: `skills` (filtro por nome),
  `plugins` (`SdkPluginConfig` local), `add_dirs`, `agents`.
- O padrão já é dogfooded no fork (`backend/src/agent.py`, caminho Claude: `prompt="/plan ..."`,
  `setting_sources=["user","project"]`).
