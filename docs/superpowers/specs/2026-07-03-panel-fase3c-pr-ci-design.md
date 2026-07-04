# Sismais AI Orquestrador — Fase 3c: validate_ci → PR draft → espera CI → ready-to-merge — Design

**Data:** 2026-07-03
**Status:** Aprovado (usuário pediu; execução autônoma)
**Relação:** Continua o runner (3b). Dá handler à coluna `validate_ci` e leva o card até `ready_to_merge`, onde
**para para o humano aprovar/mergear**. Nunca faz merge. Fecha o arco do runner antes da 3d (cortes/consolidação).

## Objetivo

Quando o card chega em `validate_ci` (review limpo), o backend: **valida local** (se houver `validateCommand`),
**dá push** na branch, **abre PR draft** (`gh`), **espera a CI**, e — verde (ou sem CI) — **avança pra
`ready_to_merge` e para**. Falha de CI → **ci-triage**: se `related`, corrige (implementer) → push → re-espera; se
`unrelated`/flaky, registra e segue. Guardrails: branch de feature sempre; **nunca `main`; nunca merge**.

## Decisões

1. **`validate_ci` vira um estágio com handler próprio (git/gh, não um agente único).** O dispatcher do pipeline
   roteia: `plan|implement|review` → `run_stage` (agente DevKit); `validate_ci` → `run_validate_ci` (orquestração
   git/gh + dispatches pontuais de agente). `has_stage` passa a incluir `validate_ci`.
2. **Mecânica git/gh isolada em `services/pr_service.py`** (subprocess puro, testável): `push_branch`,
   `create_or_get_pr(draft=True)`, `pr_url`, `check_status` (via `gh pr view --json statusCheckRollup`).
3. **Validação local com fix-loop.** Se `project.validateCommand`: roda na worktree; falhou → implementer corrige →
   commit → revalida (teto `maxIterations`). Não convergiu → **pausa**. `validateCommand` nulo (ex.: spike) → pula.
4. **PR draft.** `gh pr create --draft` (branch atual da worktree). Idempotente: se já existe PR pra branch, reusa a
   URL (`gh pr view`). URL guardada na `Execution.result` + logada (`PR: <url>`), transmitida ao board.
5. **Espera CI (bounded).** Poll de `check_status` a cada ~15s (teto de N polls). Estados: `none` (sem checks →
   trata como verde), `pending`, `pass`, `fail`. Em `fail`: para cada check falho, pega o log e despacha
   **ci-triage** (`sismais-dev-ci-triage`, novo em `STAGE_AGENTS`) com log+diff → `{verdict}`. `related` → implementer
   corrige → commit → push → re-espera (teto). `unrelated`/flaky → registra e segue. Estouro do teto → pausa.
6. **Para em `ready_to_merge`.** Verde/sem-CI/só-unrelated → move o card pra `ready_to_merge`, loga a URL do PR + uma
   sugestão de merge (squash), e **encerra o run com sucesso**. **Não** promove `gh pr ready` nem faz merge (decisão do
   humano). (Promoção a ready/merge = fora de escopo; a coluna `ready_to_merge` é o ponto de parada.)
7. **Ações de alto impacto = só no repo-alvo de teste.** Push/PR reais só em `maiconsaraiva/spike-loop-test` (que
   ganha um workflow de CI mínimo pra exercitar o caminho verde).

## Arquitetura / componentes

**Backend**
- `services/pr_service.py` (novo) — helpers `push_branch(worktree, branch)`, `create_or_get_pr(worktree, base, title,
  body)`, `get_pr_url(worktree)`, `check_status(worktree) -> {"state","failing":[...]}`. Subprocess `git`/`gh`, cwd=worktree.
- `services/stage_runner.py` — `STAGE_AGENTS["ci-triage"] = ("sismais-dev-ci-triage", [Read,Glob,Grep,Bash])`;
  `build_stage_prompt("ci-triage", ..., extra={ci_log, diff})`.
- `services/findings.py` — `parse_ci_verdict(text) -> {"verdict","porque"}` (tolerante).
- `services/pipeline_service.py` — dispatcher por coluna; `run_validate_ci(...)` (validação local + push + PR + espera
  CI + ci-triage/fix-loop + avanço p/ ready_to_merge). Reusa `finish_pause`, `_LogSink`, `gm.commit_all`, `stage_fn`.
- `routes/runner.py` — `GET .../execution` já devolve `result`/logs (o front lê a URL do PR de lá).

**Frontend**
- `api/pipeline.ts` — `getExecution` já traz `execution` (incluir `result`/`prUrl` no shape).
- `components/Card` / `CardEditModal` — quando há PR, mostrar **link "Ver PR"** (na aba Interação/Logs ou no card).

## Data flow

review limpo → card em `validate_ci` → `run_validate_ci`: (valida local↺fix) → push → PR draft (URL) → poll CI →
[fail → ci-triage → related? fix→push→re-poll : segue] → verde → card→`ready_to_merge`, loga URL+sugestão, run
`success`. Front mostra o link do PR.

## Testes

- **Backend unit:** `pr_service` com `git`/`gh` fakeados (push ok/fail; PR novo vs existente; check_status
  none/pass/pending/fail). `parse_ci_verdict`. `run_validate_ci` com stubs (sem CI → ready_to_merge; CI fail+related →
  fix+repush+repoll→ready; teto → pausa). `run_pipeline` chega em `ready_to_merge` no caminho feliz.
- **Smoke real (spike-loop-test + CI mínima):** card pequeno → pipeline até `validate_ci` → push + PR draft aberto →
  CI verde → card em `ready_to_merge` com link do PR; **PR fica aberto (draft), sem merge**. Limpar PRs/branches depois.
- **QA visual:** card em ready_to_merge mostra o link do PR; nada de merge automático.

## Critérios de aceitação

1. `validate_ci` roda: valida local (se houver), push, **abre PR draft**, guarda a URL.
2. Espera a CI; verde/sem-CI → card em **`ready_to_merge`** e run `success`; a URL do PR aparece no board.
3. CI vermelha `related` → corrige, push, re-espera; `unrelated` → registra e segue; estouro → pausa.
4. **Nunca** faz merge nem promove o PR a ready; para no ready_to_merge.
5. Testes de backend passam; smoke real deixa um PR draft aberto no spike-loop-test; sem regressão nas fases anteriores.

## Fora de escopo

Promover PR a ready / merge; políticas de PR por projeto (draft vs ready); resolução de conflito de merge; múltiplos PRs
por card; **incremento 2 do chat ao vivo** (`/say`); Fase 3d (cortes/consolidação).
