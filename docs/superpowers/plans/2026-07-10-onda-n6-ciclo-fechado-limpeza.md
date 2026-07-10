# Onda N6 — Fechar o ciclo no board + limpeza da UI legada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) O board detecta o merge do PR e move o card de `ready_to_merge` para `done` sozinho — hoje o merge acontece no GitHub e o card fica "cego", exigindo drag manual. (B) Remover a UI legada morta do Card (dois vocabulários de status conviviam) — item de remoção explícito e planejado da revisão estratégica, seguro porque `PipelineControls` já é o substituto vivo. Dimensão 8.

**Architecture (A):** `pr_service.get_pr_state(worktree)` consulta `gh pr view --json state` (OPEN/MERGED/CLOSED). Endpoint `POST .../cards/{cid}/check-merge`: só para card em `ready_to_merge` com `worktree_path`; se MERGED → move o card para `done` (validado pelo config, idempotente), broadcast `card_moved`; retorna `{merged, state}`. O front (PipelineControls) faz poll leve (a cada ~20s) SÓ enquanto o card `ready_to_merge` está montado + botão "Verificar merge"; o card se move via o broadcast WS existente. **Nunca faz merge** — só detecta o merge feito pelo humano no GitHub (respeita a regra inegociável).

**Architecture (B):** remoção cirúrgica guiada pelo mapa abaixo; `PipelineControls` (vivo) permanece. `useWorkflowAutomation` é inteiramente morto; `useAgentExecution` é morto exceto `fetchLogs`/`fetchLogsHistory` (que só servem a UI legada — saem junto). Gate: `npx tsc --noEmit` deve terminar no baseline (≤ 3 erros TS6133 pré-existentes; pode DIMINUIR se `cardRef` for removido — menos é ok, diferente/mais não). NÃO remover o tipo `MergeStatus` nem `card.mergeStatus` (usados por `BranchesDropdown`, fora de escopo).

**Estado (pós-N5):** worktree do card sobrevive pós-ready_to_merge (sem auto-cleanup); `Execution.result` = URL do PR, exposto como `prUrl`; `card_ws_manager.broadcast_card_moved` já atualiza o board; `card_repository.move` valida por config e seta `completed_at` em `done`.

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes — ignorar). Front: `cd frontend && npx tsc --noEmit`. Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: detecção de merge no backend

**Files:**
- Modify: `backend/src/services/pr_service.py` (`get_pr_state`)
- Modify: `backend/src/routes/runner.py` (endpoint `check-merge`)
- Test: `backend/tests/test_pr_service.py`, `backend/tests/test_check_merge_route.py` (novo)

- [ ] **Step 1.1: Write the failing tests**

Em `backend/tests/test_pr_service.py` (siga o padrão de mock de subprocess do arquivo — provavelmente monkeypatcha `_run`):

```python
async def test_get_pr_state_merged(monkeypatch):
    from src.services import pr_service
    async def fake_run(args, cwd):
        return 0, '{"state": "MERGED"}', ""
    monkeypatch.setattr(pr_service, "_run", fake_run)
    assert await pr_service.get_pr_state("/wt") == "MERGED"


async def test_get_pr_state_open(monkeypatch):
    from src.services import pr_service
    async def fake_run(args, cwd):
        return 0, '{"state": "OPEN"}', ""
    monkeypatch.setattr(pr_service, "_run", fake_run)
    assert await pr_service.get_pr_state("/wt") == "OPEN"


async def test_get_pr_state_sem_pr(monkeypatch):
    from src.services import pr_service
    async def fake_run(args, cwd):
        return 1, "", "no pull requests found"
    monkeypatch.setattr(pr_service, "_run", fake_run)
    assert await pr_service.get_pr_state("/wt") == "UNKNOWN"
```

Criar `backend/tests/test_check_merge_route.py` (siga o padrão httpx/ASGITransport de `test_projects_registry_routes.py` + monkeypatch do `async_session_maker`; leia um teste de rota existente que crie project+card e move para `ready_to_merge`):

```python
# Esqueleto — adapte à infra de teste de rotas do repo (fixture client + session maker).
# Cenário: card em ready_to_merge + get_pr_state monkeypatchado.
# - MERGED  -> resposta {merged: True}, card vai para 'done'.
# - OPEN    -> {merged: False, state: "OPEN"}, card permanece em ready_to_merge.
# - card fora de ready_to_merge -> 409 ou {merged: False} sem mover (escolha e teste).
```

(se a infra de teste de rota com pipeline for pesada, cubra `get_pr_state` no nível de service + um teste de rota mínimo do caminho OPEN/estado inválido; documente no report.)

- [ ] **Step 1.2:** Rodar — Expected: FAIL.

- [ ] **Step 1.3: `get_pr_state`** — em `backend/src/services/pr_service.py`, após `get_pr_url`:

```python
async def get_pr_state(worktree: str) -> str:
    """Estado do PR da branch atual: 'OPEN' | 'MERGED' | 'CLOSED' | 'UNKNOWN'.

    Detecta o merge feito pelo humano no GitHub — o orquestrador NUNCA faz merge."""
    rc, out, _ = await _run(["gh", "pr", "view", "--json", "state"], cwd=worktree)
    if rc != 0:
        return "UNKNOWN"
    try:
        state = (json.loads(out) or {}).get("state")
    except (json.JSONDecodeError, ValueError):
        return "UNKNOWN"
    return state if state in ("OPEN", "MERGED", "CLOSED") else "UNKNOWN"
```

- [ ] **Step 1.4: Endpoint** — em `backend/src/routes/runner.py`, adicionar (leia como as rotas existentes obtêm card/projeto e broadcast; reuse os helpers). Esqueleto:

```python
@router.post("/{card_id}/check-merge")
async def check_merge(project_id: str, card_id: str, db: AsyncSession = Depends(get_db)):
    """Detecta se o PR do card foi mergeado (no GitHub) e, se sim, move o card para 'done'.
    Idempotente; so age em card em ready_to_merge com worktree. Nunca faz merge."""
    repo = CardRepository(db)
    card = await repo.get_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.column_id != "ready_to_merge":
        return {"merged": card.column_id == "done", "state": "N/A"}
    if not card.worktree_path:
        return {"merged": False, "state": "UNKNOWN"}
    from ..services.pr_service import get_pr_state
    state = await get_pr_state(card.worktree_path)
    if state != "MERGED":
        return {"merged": False, "state": state}
    prev = card.column_id
    moved, err = await repo.move(card_id, "done")
    await db.commit()
    if err:
        return {"merged": True, "state": state, "moved": False, "error": err}
    # broadcast igual ao pipeline (front atualiza o board sozinho)
    try:
        from ..schemas.card import CardResponse
        from ..services.card_ws import card_ws_manager
        card_dict = CardResponse.model_validate(moved).model_dump(by_alias=True, mode="json")
        await card_ws_manager.broadcast_card_moved(card_id, prev, "done", card_dict)
    except Exception:  # noqa: BLE001
        pass
    return {"merged": True, "state": state, "moved": True}
```

(confirme imports de `CardRepository`/`HTTPException`/`AsyncSession`/`Depends`/`get_db` já presentes no arquivo — provavelmente sim.)

- [ ] **Step 1.5:** `pytest tests/test_pr_service.py tests/test_check_merge_route.py -v` — PASS. Suíte completa.

- [ ] **Step 1.6: Commit**

```bash
git add backend/src/services/pr_service.py backend/src/routes/runner.py backend/tests/test_pr_service.py backend/tests/test_check_merge_route.py
git commit -m "feat(board): deteccao de merge do PR — check-merge move o card para done (N6)"
```

---

### Task 2: poll de merge no PipelineControls

**Files:**
- Modify: `frontend/src/api/pipeline.ts` (client `checkMerge`)
- Modify: `frontend/src/components/PipelineControls/PipelineControls.tsx`

- [ ] **Step 2.1: Client** — em `frontend/src/api/pipeline.ts`, adicionar:

```typescript
/** Detecta se o PR do card foi mergeado no GitHub; se sim, o backend move o card para done. */
export async function checkMerge(projectId: string, cardId: string): Promise<{ merged: boolean; state?: string }> {
  const response = await fetch(`${base(projectId, cardId)}/check-merge`, { method: 'POST' });
  if (!response.ok) return { merged: false };
  return response.json();
}
```

- [ ] **Step 2.2: Poll + botão** — em `frontend/src/components/PipelineControls/PipelineControls.tsx`:

1. Import `checkMerge`.
2. Novo estado: `const [checkingMerge, setCheckingMerge] = useState(false);`
3. Handler:

```tsx
  const handleCheckMerge = useCallback(async () => {
    if (!projectId) return;
    setCheckingMerge(true);
    try {
      await checkMerge(projectId, card.id);  // se merged, o backend move o card (chega via WS card_moved)
    } catch { /* ignore */ }
    finally { setCheckingMerge(false); }
  }, [projectId, card.id]);
```

4. Poll leve enquanto o card está em `ready_to_merge` (montado):

```tsx
  useEffect(() => {
    if (card.columnId !== 'ready_to_merge' || !projectId) return;
    const id = setInterval(() => { handleCheckMerge(); }, 20000);
    return () => clearInterval(id);
  }, [card.columnId, projectId, handleCheckMerge]);
```

5. Botão junto do link "Ver PR" (dentro do bloco que renderiza quando há `prUrl`, ou ao lado): um botão "Verificar merge" que chama `handleCheckMerge` (disabled enquanto `checkingMerge`). Mantenha o link "Ver PR" existente.

- [ ] **Step 2.3:** `npx tsc --noEmit` — baseline.

- [ ] **Step 2.4: Commit**

```bash
git add frontend/src/api/pipeline.ts frontend/src/components/PipelineControls/PipelineControls.tsx
git commit -m "feat(board): PipelineControls verifica merge do PR (poll leve + botao) e o card fecha sozinho (N6)"
```

---

### Task 3: remover a UI legada do Card (remoção cirúrgica)

Item de remoção explícito. **Gate absoluto:** `npx tsc --noEmit` no baseline após CADA arquivo tocado — o TypeScript é a rede: se um prop removido deixar referência órfã, o tsc quebra. Trabalhe arquivo por arquivo, rodando tsc entre eles.

**Files (cascata):**
- Modify: `frontend/src/components/Card/Card.tsx`
- Modify: `frontend/src/components/Column/Column.tsx`
- Modify: `frontend/src/components/Board/Board.tsx`
- Modify: `frontend/src/pages/KanbanPage.tsx`
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/hooks/useWorkflowAutomation.ts` (inteiramente morto)
- Modify: `frontend/src/hooks/useAgentExecution.ts` (remover métodos mortos; manter só se algo vivo restar) OU deletar se nada vivo restar
- Modify: `frontend/src/api/config.ts` (bloco `execution` legado)

**Mapa do que é MORTO (remover) — verificado por exploração:**

- **`Card.tsx`:** `getStatusClass` (def 68-76), `getExecutionMessage` (117-189), badges de execução + "View Logs" legado (250-308), botão "Create PR" placeholder (334-354), "View Logs" do done (355-374), barra `workflowProgress` (377-388), `failedBanner` (221-225, `mergeStatus === 'failed'` — nada seta), `LogsModal` legado (390-402), `useEffect` de histórico (81-92), props `executionStatus`/`workflowStatus`/`onRunWorkflow`/`fetchLogsHistory` (tipos 18-21, destructure 25). **PRESERVAR:** `PipelineControls` (333), `ExpertBadges` (211-217), imagens (226-249), `tokenStats`/`costStats` (309-320), selo paused (323-331), `CardEditModal` (403-411), props `card`/`onRemove`/`onUpdateCard`/`isDragging`/`isLoadingExperts`.
- **`Column.tsx`:** props `executionStatus`/`workflowStatus`/`onRunWorkflow` (6-21, repasse 61-65) — remover o repasse ao Card.
- **`Board.tsx`:** props legadas (14, 23, 84) — remover.
- **`KanbanPage.tsx`:** props legadas (21, 45, 85, 735-736) — remover.
- **`App.tsx`:** instanciação de `useAgentExecution` (84) e `useWorkflowAutomation` (125-144); construção de `initialExecutions`/`initialWorkflowStatuses` (231-315 — a parte que alimenta os hooks legados); poll de merge morto (396-462); bloco `AUTO_RUN_ON_DRAG` + `const AUTO_RUN_ON_DRAG` (22, 623-714); passagem das props legadas (737). **PRESERVAR:** poll de token stats (342-394, VIVO — lê `card.activeExecution` real), `useCardWebSocket`, toast de pausa (N3-A3), `moveCard`, `handleDragEnd` (menos o bloco morto).
- **`api/config.ts`:** bloco `execution` (72-79) — remover (nenhum consumidor vivo).
- **`useAgentExecution.ts` / `useWorkflowAutomation.ts`:** `useWorkflowAutomation` deletar por inteiro. `useAgentExecution`: `fetchLogs`/`fetchLogsHistory` só servem a UI legada do Card (que sai) → deletar o hook inteiro TAMBÉM, a menos que o tsc acuse um consumidor vivo (nesse caso, manter só o vivo e documentar).

**Passos:**

- [ ] **Step 3.1:** Baseline: `cd frontend && npx tsc --noEmit` — anotar os erros exatos (3 TS6133 esperados) para comparar no fim.

- [ ] **Step 3.2:** `Card.tsx` — remover todos os blocos MORTOS listados e as 4 props legadas (tipo + destructure). Rodar `npx tsc --noEmit` — vai acusar os pais que ainda passam as props removidas (esperado); anote-os.

- [ ] **Step 3.3:** `Column.tsx`, `Board.tsx`, `KanbanPage.tsx` — remover o repasse das props legadas (tipos + JSX). tsc após cada um.

- [ ] **Step 3.4:** `App.tsx` — remover: bloco `AUTO_RUN_ON_DRAG` (const + `if`), poll de merge morto (396-462), instanciação dos hooks legados + as props passadas a KanbanPage, e a construção de `initialWorkflowStatuses`/parte legada de `initialExecutions` que só alimentava os hooks removidos. CUIDADO: preservar o poll de token stats (342-394) e o `initialExecutions` na parte que alimenta `card.activeExecution`/tokenStats se ainda houver consumidor vivo — se não houver, remover. tsc.

- [ ] **Step 3.5:** Deletar `useWorkflowAutomation.ts`; deletar (ou podar) `useAgentExecution.ts`; remover o bloco `execution` de `api/config.ts`. tsc.

- [ ] **Step 3.6:** `npx tsc --noEmit` FINAL — deve estar no baseline (≤ 3 erros TS6133; se `cardRef` de `Card.tsx:31` sumiu na limpeza, 2 erros — ok). NENHUM erro novo/diferente. Se aparecer erro novo, é referência órfã — resolver.

- [ ] **Step 3.7:** Verificação de resíduo: `grep -rn "execute-plan\|useWorkflowAutomation\|getWorkflowStatus\|executionStatus\|onRunWorkflow" frontend/src` — só devem sobrar (se algo) menções em `types/index.ts` (definições de tipo que outras features usam) e comentários; nenhum call site vivo. Documentar o que sobrou e por quê.

- [ ] **Step 3.8: Commit**

```bash
git add -A frontend/src
git commit -m "refactor(painel): remove a UI de execucao legada do Card e os hooks/endpoints mortos — PipelineControls e a fonte unica (N6)"
```

---

### Task 4: suite completa + docs

- [ ] **Step 4.1:** Suíte completa backend (`| tail -3`) + `npx tsc --noEmit` (baseline). Confirmar que nenhum teste de frontend/backend quebrou.

- [ ] **Step 4.2:** Em `docs/ARQUITETURA_E_ESTADO.md`, após a N5:

```markdown
### Onda N6 — ciclo fechado no board + limpeza da UI legada — feito 2026-07-10
- **Merge detectado:** `pr_service.get_pr_state` (`gh pr view --json state`) + endpoint
  `POST .../cards/{cid}/check-merge` move o card `ready_to_merge → done` quando o PR foi mergeado
  no GitHub (idempotente; **nunca faz merge** — só detecta o do humano). PipelineControls faz poll
  leve (20s) enquanto o card está em ready_to_merge + botão "Verificar merge"; o card fecha via WS.
- **UI legada removida:** o Card perdeu os badges/mensagens de execução legados ("Executing /plan…",
  barra "Planning…"), o botão "Create PR" placeholder, o "View Logs" legado e o banner de merge morto;
  `useWorkflowAutomation` e `useAgentExecution` (hooks mortos), o bloco `AUTO_RUN_ON_DRAG`, o poll de
  merge morto e os endpoints `execute-*` inexistentes foram apagados. `PipelineControls` é a fonte
  única de execução/PR/logs do card. (Dívida do fork registrada no ARQUITETURA resolvida.)
- Plano: `plans/2026-07-10-onda-n6-ciclo-fechado-limpeza.md`.
```

Também remover, na seção "3d-final", a linha de dívida "**Dívida frontend restante:** `useAgentExecution` + a UI de execução legada no `Card` ainda chamam `/api/execute-*`…" (agora resolvida) — substituir por "(resolvida na onda N6)".

- [ ] **Step 4.3: Commit**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda N6 (ciclo fechado + limpeza da UI legada)"
```

## Self-review (feito na escrita)

- Parte A é aditiva e respeita a regra inegociável (nunca faz merge — só detecta): `get_pr_state` é read-only; o move para done é a mesma transição do drag manual, agora automatizada pós-merge-humano.
- Parte B é a remoção explícita prevista na revisão; `PipelineControls` cobre execução/PR/logs (inclusive de cards done, via `getExecution` + branchName), então nenhuma capacidade viva se perde. O `tsc` é o gate objetivo contra referência órfã; a cascata de props está mapeada arquivo:linha.
- `MergeStatus`/`card.mergeStatus` preservados (BranchesDropdown depende). Poll de token stats preservado (vivo).
- Risco residual: sem rodar o app, a verificação é tsc + review de diff. Aceitável para remoção de código comprovadamente morto (endpoints inexistentes, props não-consumidas). Um smoke real do board é recomendável quando o usuário rodar a app (fora do escopo desta sessão, que não gasta Max).
