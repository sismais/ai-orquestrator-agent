# CLAUDE.md — Sismais AI Orquestrador

Bootstrap para o Claude Code neste repo. Regras de alta frequência aqui; **detalhe nos docs**.

## O que é (1 parágrafo)

Painel Kanban que **dirige agentes de IA** (o **Sismais AI DevKit**) sobre projetos reais: o **backend
orquestra** a execução de cada coluna numa **git worktree isolada por card**, com logs, e **para no
ready-to-merge** para o humano aprovar/mergear. **Nunca faz merge sozinho.** É um **fork do Zenflow** em
reforma — muito código legado existe mas está desligado/adiado; confie nos docs abaixo, não no comportamento antigo.

## Leia primeiro (docs canônicos)

- **`docs/ARQUITETURA_E_ESTADO.md`** — arquitetura atual, o que está ativo vs cortado/adiado, **estado das
  fases + roadmap** (próximo: Fase 3b-resto → 3c → 3d), arquivos-chave, bugs de baseline.
- **`docs/DESENVOLVIMENTO.md`** — como rodar backend (:3001) / frontend (:5173), testes, **gotchas**
  (zumbis na porta, WAL, `.env`), repo-alvo de teste, fluxo git.
- **`docs/superpowers/{specs,plans,notes}/`** — design/planos por fase; nota **`fork-code-map.md`** mapeia
  o código para as próximas fases. Ao retomar uma fase, comece pelo spec/plan dela.

## Regras sempre ativas

- **Banco único** `backend/orchestrator.db` (via `DATABASE_URL`), **tenant-shaped** por `project_id`.
  Nada de voltar ao multi-arquivo/`ActiveProject` (legado, sai na 3d). Supabase-ready por troca de URL.
- **Auth do SDK = assinatura Max do CLI** (sem `ANTHROPIC_API_KEY`). Execução real **gasta Max** — teste
  só no repo-alvo **`maiconsaraiva/spike-loop-test`**.
- **Backend orquestra; coluna = etapa.** Workflow é **config** (tabela `Workflow`, seed `dev`); board e
  validação de move vêm do config, não hardcoded.
- **DevKit** vive em `devkit/.claude/`; o runner o carrega copiando pra worktree (não é plugin instalável).
- **Método de evolução:** superpowers (brainstorm → spec → plano → execução com review). Specs/planos em
  `docs/superpowers/`. Trabalho **direto na `main`** deste fork privado.
- **Preserve o que funciona.** Legado desligado ≠ apagar sem plano — remoção é item explícito (3d).

## Rodar (resumo)

```bash
cd backend && ./venv/Scripts/python.exe -m src.main    # :3001 (Windows/Git Bash)
cd frontend && npm run dev                             # :5173
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v
```
Detalhe e gotchas: `docs/DESENVOLVIMENTO.md`.
