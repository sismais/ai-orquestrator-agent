# CLAUDE.md — Sismais AI Orquestrador

Bootstrap para o Claude Code neste repo. Regras de alta frequência aqui; **detalhe nos docs**.

## O que é (1 parágrafo)

Painel Kanban que **dirige agentes de IA** (o **Sismais AI DevKit**) sobre projetos reais: o **backend
orquestra** a execução de cada coluna numa **git worktree isolada por card**, com logs, e **para no
ready-to-merge** para o humano aprovar/mergear. **Nunca faz merge sozinho.** É um **fork do Zenflow** em
reforma — o grosso do legado já foi **cortado** (algum resíduo inerte pode existir); confie nos docs abaixo, não no comportamento antigo.

## Leia primeiro (docs canônicos)

- **`docs/ARQUITETURA_E_ESTADO.md`** — arquitetura atual, o que está ativo vs removido, **estado das
  fases + roadmap**, arquivos-chave, bugs de baseline.
- **`docs/DESENVOLVIMENTO.md`** — como rodar backend (:3001) / frontend (:5173), testes, **gotchas**
  (zumbis na porta, WAL, `.env`), repo-alvo de teste, fluxo git.
- **`docs/sismais-devkit/{specs,plans,notes,prompts}/`** — design/planos por fase; nota
  **`fork-code-map.md`** mapeia o código para as próximas fases. Ao retomar uma fase, comece
  pelo spec/plan dela.

## Regras sempre ativas

- **Banco único** `backend/orchestrator.db` (via `DATABASE_URL`), **tenant-shaped** por `project_id`.
  O multi-arquivo/`ActiveProject` legado **foi removido** — não voltar. Supabase-ready por troca de URL.
- **Auth do SDK = assinatura Max do CLI** (sem `ANTHROPIC_API_KEY`). Execução real **gasta Max** — teste
  só no repo-alvo **`maiconsaraiva/spike-loop-test`**.
- **Backend orquestra; coluna = etapa.** Workflow é **config** (tabela `Workflow`, seed `dev`); board e
  validação de move vêm do config, não hardcoded.
- **DevKit** vive em `devkit/.claude/`; o runner **NÃO copia** pra worktree — o papel de cada estágio vem do
  `system_prompt` (lê o `.md` do agente), e a worktree fica pristina (o `.claude` do projeto commita normal).
- **Projeto irmão (fonte dos prompts):** os `devkit/.claude/agents/*.md`, `devkit/schemas/` e
  `devkit/templates/` são **cópias sincronizadas** do `devkit-core/` do repo
  `sismais/sismais-ai-plugins-private` (checkout local:
  `d:\Sismais\Fontes\sismais-ai-plugins-workspace\sismais-ai-plugins-private`). Lá também vivem os
  **plugins do modo terminal** (mesmos agentes via Claude Code CLI/VS Code). Regra de fronteira:
  **prompt/agente/contrato → edita LÁ** (`devkit-core` + `node devkit-core/sync.mjs --platform <este repo>`);
  **motor/UI/pipeline → edita AQUI**. Editar as cópias locais quebra
  `backend/tests/test_devkit_core_contract.py`.
- **Método de evolução:** superpowers (brainstorm → spec → plano → execução com review). Specs/planos em
  `docs/sismais-devkit/`. Trabalho **direto na `main`** deste fork privado.
- **Preserve o que funciona.** Remoção de algo existente é sempre item explícito e planejado, nunca embutida.

## Rodar (resumo)

```bash
cd backend && ./venv/Scripts/python.exe -m src.main    # :3001 (Windows/Git Bash)
cd frontend && npm run dev                             # :5173
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v
```
Detalhe e gotchas: `docs/DESENVOLVIMENTO.md`.
