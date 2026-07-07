# Remoção do subsistema legado (Fase C) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover por completo o subsistema legado de "projeto ativo" — migrar os endpoints de worktree/git e o experts-triage para o `Project` do registry, repontar o FK do metrics, e apagar `ActiveProject`, `database_manager`, `project_history`, `project_manager`, `routes/projects.py` e o `ExpertsModal` órfão.

**Architecture:** O pipeline/runner já abandonou o `ActiveProject` — recebe `project_id` e resolve `Project` via `ProjectRepository`, instanciando `GitWorkspaceManager(project.path)`. Este plano estende esse padrão aos 4 endpoints de worktree/git em `main.py` e ao `expert-triage`, e então remove o modelo antigo. SQLite **sem FK enforcement** (nenhum `PRAGMA foreign_keys=ON`) e tabelas `active_project`/`project_metrics`/`execution_metrics` **vazias** — sem dado a migrar.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, pytest; React 18 (frontend só validado via `npm run build`).

**Dependência:** Requer o Plano 1 concluído (Fases B e D tiram o chat e o Gemini do `ActiveProject`). Após este plano, `grep -ri activeproject backend/src` deve voltar vazio.

**Repo:** `D:/Sismais/Fontes/ai-orquestrator-agent`.

**Ordem interna:** C1 (worktree/git → registry) → C2 (FK metrics) → C3 (experts-triage) → C4 (dropar o legado). C4 por último porque depende de C1/C3 terem removido os usos vivos.

**Endpoints — forma escolhida:** manter os paths atuais e adicionar `project_id` como **query param** (padrão mínimo, o front só apenda `?project_id=`, lido de `localStorage 'orq.currentProjectId'` como o `PipelineControls` já faz). Sem projeto → resposta graciosa (lista de branches vazia), não 400.

---

## C1 — Worktree/git resolvem o projeto pelo registry

Os 4 endpoints em `main.py` deixam de usar `get_active_project(db)` e passam a resolver `Project` por `project_id`.

### Task C1.1: Migrar os endpoints de worktree/git em main.py

**Files:**
- Modify: `backend/src/main.py`

- [ ] **Step 1: `GET /api/git/branches` — resolver por project_id (query)**

Trocar o handler (linhas ~309-339) por:
```python
@app.get("/api/git/branches")
async def list_git_branches(project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    """Lista as branches do repo do projeto selecionado (registry)."""
    project_path = None
    if project_id:
        from .repositories.project_repository import ProjectRepository
        project = await ProjectRepository(db).get_by_id(project_id)
        if project:
            project_path = project.path
    if not project_path:
        return {"success": True, "branches": [], "defaultBranch": "main"}

    git_dir = Path(project_path) / ".git"
    if not git_dir.exists():
        return {"success": True, "branches": [], "defaultBranch": "main"}

    git_manager = GitWorkspaceManager(project_path)
    branches = await git_manager.list_all_branches()
    return {
        "success": True,
        "branches": branches,
        "defaultBranch": await git_manager._get_default_branch(),
    }
```

- [ ] **Step 2: `GET /api/branches` — resolver por project_id (query)**

Trocar o handler (linhas ~256-288) para receber `project_id: str | None = None` e substituir `project = await get_active_project(db)` + o 400 por:
```python
    if not project_id:
        return {"branches": []}
    from .repositories.project_repository import ProjectRepository
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        return {"branches": []}
    git_manager = GitWorkspaceManager(project.path)
```
(manter o restante — `list_active_worktrees()` + enriquecimento com Card.)

- [ ] **Step 3: `POST /api/cards/{card_id}/workspace` — resolver por project_id (body)**

No handler (linhas ~200-253), trocar `project = await get_active_project(db)` + o 400 por resolução via `request_body["projectId"]`:
```python
    project_id = (request_body or {}).get("projectId")
    if not project_id:
        raise HTTPException(status_code=400, detail="projectId obrigatório")
    from .repositories.project_repository import ProjectRepository
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
```
(manter o restante — checagem `.git`, `GitWorkspaceManager(project.path)`, `create_worktree`, update do card.)

- [ ] **Step 4: `POST /api/cleanup-orphan-worktrees` — resolver por project_id (query)**

No handler (linhas ~291-306), trocar `project = await get_active_project(db)` + o 400 por `project_id: str | None = None` na assinatura e:
```python
    if not project_id:
        raise HTTPException(status_code=400, detail="projectId obrigatório")
    from .repositories.project_repository import ProjectRepository
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
```
(manter o restante — `select(Card.id)`, `GitWorkspaceManager(project.path)`, `cleanup_orphan_worktrees`.)

> NÃO remover ainda o helper `get_active_project` nem o import de `ActiveProject` — isso é o C4 (depois que nada mais os usa).

- [ ] **Step 5: Verificar import do backend**

Run: `cd backend && python -c "import src.main"`
Expected: sem erro.

- [ ] **Step 6: Commit**

```bash
git add backend/src/main.py
git commit -m "refactor(worktree): endpoints de worktree/git resolvem projeto pelo registry (project_id)"
```

### Task C1.2: Frontend passa project_id aos endpoints de branches

**Files:**
- Modify: `frontend/src/api/git.ts`
- Modify: `frontend/src/components/AddCardModal/AddCardModal.tsx`
- Modify: `frontend/src/components/BranchesDropdown/BranchesDropdown.tsx`

- [ ] **Step 1: git.ts — fetchGitBranches recebe projectId**

Trocar `fetchGitBranches` por:
```ts
export async function fetchGitBranches(projectId: string | null): Promise<BranchesResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  const response = await fetch(`${API_CONFIG.BASE_URL}/api/git/branches${qs}`);
  // ...resto inalterado (parse do JSON, retorno)
}
```

- [ ] **Step 2: AddCardModal — passar o projeto do localStorage**

No `AddCardModal.tsx`, no `loadBranches` (linha ~169-172), ler o projeto atual e passar:
```tsx
const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
const response = await fetchGitBranches(projectId);
```

- [ ] **Step 3: BranchesDropdown — passar project_id na URL**

No `BranchesDropdown.tsx` (linha ~29), trocar `fetch(API_ENDPOINTS.branches)` por:
```tsx
const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
const response = await fetch(`${API_ENDPOINTS.branches}${qs}`);
```

- [ ] **Step 4: Verificar typecheck**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 5: Smoke — branch selector do AddCard**

Com backend rodando e o projeto de testes (**apenas `maiconsaraiva/spike-loop-test`**) selecionado: abrir "novo card" e conferir que o dropdown de branches lista as branches do repo selecionado. Trocar de projeto e reabrir → branches do outro repo.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/git.ts frontend/src/components/AddCardModal/AddCardModal.tsx frontend/src/components/BranchesDropdown/BranchesDropdown.tsx
git commit -m "feat(worktree): front manda project_id ao listar branches"
```

---

## C2 — Repontar o FK do metrics para projects.id

### Task C2.1: FK do metrics → projects.id + migração leve idempotente

**Files:**
- Modify: `backend/src/models/metrics.py`
- Modify: `backend/src/services/light_migrations.py`
- Modify: `backend/src/main.py`
- Test: `backend/tests/test_metrics_fk_migration.py`

- [ ] **Step 1: Teste — a migração repointa o FK (idempotente, roda 2x)**

```python
# backend/tests/test_metrics_fk_migration.py
import src.models  # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.services.light_migrations import migrate_metrics_fk_target


async def test_migrate_metrics_fk_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # cria as tabelas no schema ANTIGO (FK -> active_project), vazias
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE active_project (id VARCHAR PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text(
            "CREATE TABLE project_metrics (id VARCHAR PRIMARY KEY, project_id VARCHAR "
            "REFERENCES active_project(id))"
        ))
        await conn.execute(text(
            "CREATE TABLE execution_metrics (id VARCHAR PRIMARY KEY, project_id VARCHAR "
            "REFERENCES active_project(id))"
        ))
    # roda 2x
    await migrate_metrics_fk_target(engine)
    await migrate_metrics_fk_target(engine)
    async with engine.begin() as conn:
        for table in ("project_metrics", "execution_metrics"):
            fks = (await conn.execute(text(f"PRAGMA foreign_key_list({table})"))).fetchall()
            targets = {row[2] for row in fks}  # row[2] = tabela referenciada
            assert "active_project" not in targets
            assert "projects" in targets
    await engine.dispose()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_metrics_fk_migration.py -v`
Expected: FAIL (ImportError: migrate_metrics_fk_target)

- [ ] **Step 3: Repontar o FK nos models**

Em `backend/src/models/metrics.py`: trocar `ForeignKey("active_project.id")` por `ForeignKey("projects.id")` nas linhas 16 (`ProjectMetrics.project_id`) e 78 (`ExecutionMetrics.project_id`).

- [ ] **Step 4: Implementar a migração leve**

Em `backend/src/services/light_migrations.py`, adicionar:
```python
async def migrate_metrics_fk_target(engine: AsyncEngine) -> None:
    """Repointa o FK de project_metrics/execution_metrics de active_project -> projects.

    SQLite nao faz ALTER de FK; como as tabelas de metrics estao vazias em DEV, o
    caminho seguro e dropar (se ainda apontam pra active_project e estao vazias) e
    deixar o create_all recriar com o FK novo. Idempotente.
    """
    from ..database import Base
    async with engine.begin() as conn:
        for table in ("project_metrics", "execution_metrics"):
            exists = (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
            ), {"t": table})).first()
            if not exists:
                continue
            fks = (await conn.execute(text(f"PRAGMA foreign_key_list({table})"))).fetchall()
            targets = {row[2] for row in fks}
            if "active_project" not in targets:
                continue  # ja migrado
            count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
            if count and count > 0:
                # seguranca: nao dropar tabela com dados; sinaliza no log
                print(f"[light_migrations] {table} tem {count} linhas; FK nao repontado automaticamente")
                continue
            await conn.execute(text(f"DROP TABLE {table}"))
        # recria as tabelas dropadas com o FK novo
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_metrics_fk_migration.py -v`
Expected: PASS

- [ ] **Step 6: Chamar no startup**

Em `backend/src/main.py` (`lifespan`, junto às demais migrações leves), adicionar:
```python
    from .services.light_migrations import migrate_metrics_fk_target
    await migrate_metrics_fk_target(_engine)
```

- [ ] **Step 7: Verificar import + boot**

Run: `cd backend && python -c "import src.main"`
Expected: sem erro.

- [ ] **Step 8: Commit**

```bash
git add backend/src/models/metrics.py backend/src/services/light_migrations.py backend/src/main.py backend/tests/test_metrics_fk_migration.py
git commit -m "feat(metrics): repointa FK project_id -> projects.id (migracao leve idempotente)"
```

---

## C3 — Experts-triage resolve o projeto pelo card

### Task C3.1: expert-triage usa card.project_id → Project.path

**Files:**
- Modify: `backend/src/routes/experts.py`
- Test: `backend/tests/test_expert_triage_project.py`

- [ ] **Step 1: Teste — triage resolve project_path pelo card (sem ProjectManager)**

```python
# backend/tests/test_expert_triage_project.py
import inspect
import src.routes.experts as experts_mod


def test_triage_source_uses_card_project_not_manager():
    src = inspect.getsource(experts_mod.expert_triage_endpoint)
    assert "current_project" not in src  # nao usa mais o ProjectManager
    assert "project_id" in src  # resolve pelo card/registry
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_expert_triage_project.py -v`
Expected: FAIL (ainda usa `manager.current_project`)

- [ ] **Step 3: Reescrever o trecho de resolução do projeto no `expert_triage_endpoint`**

Em `backend/src/routes/experts.py`, dentro de `expert_triage_endpoint` (linhas ~254-266), trocar:
```python
    manager = get_project_manager()
    project_path = str(manager.current_project) if manager.current_project else None
    cwd = project_path if project_path else str(Path.cwd().parent)
```
por:
```python
    # Resolve o projeto pelo card (registry), nao mais pelo ProjectManager.
    card_repo = CardRepository(db)
    card = await card_repo.get_by_id(request.card_id)
    project_path = None
    if card and card.project_id:
        from ..repositories.project_repository import ProjectRepository
        project = await ProjectRepository(db).get_by_id(card.project_id)
        if project:
            project_path = project.path
    cwd = project_path if project_path else str(Path.cwd().parent)
```
(O restante do endpoint — `identify_experts(...)`, persistência via `CardRepository.update_experts` — fica igual.)

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_expert_triage_project.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/routes/experts.py backend/tests/test_expert_triage_project.py
git commit -m "refactor(experts): expert-triage resolve o projeto pelo card (registry)"
```

---

## C4 — Dropar o subsistema legado

Agora que nada vivo usa `ActiveProject`/`ProjectManager`/history-DB, remover tudo. Ordem: (a) endpoints do modal órfão + ExpertsModal; (b) routes/projects.py + imports; (c) project_manager + database_manager + project_history + get_history_db; (d) ActiveProject; (e) testes órfãos.

### Task C4.1: Remover os endpoints do modal órfão de experts + ExpertsModal

**Files:**
- Modify: `backend/src/routes/experts.py`
- Delete: `frontend/src/components/ExpertsModal/` (pasta inteira)

- [ ] **Step 1: Remover os 4 endpoints do modal em experts.py**

Apagar de `backend/src/routes/experts.py` os handlers: `analyze_codebase_for_experts` (`GET /experts/analyze`, ~60-95), `create_experts` (`POST /experts/create`, ~98-147), `delete_expert` (`DELETE /experts/{expert_id}`, ~150-189), `get_experts_status` (`GET /experts/status`, ~192-229). Manter `expert_triage_endpoint`, `expert_sync_endpoint`, `update_card_experts`.

- [ ] **Step 2: Remover imports agora órfãos**

Em `experts.py`, remover os imports que só serviam ao modal: `from .projects import get_project_manager` (linha 24), `from ..config.experts import get_experts, clear_experts_cache` (linha 23), `from ..services.expert_init_service import expert_init_service` (linha 22) e os schemas do modal não usados por triage/sync (conferir quais de `..schemas.expert` sobram). Remover `CreateExpertsRequest`/`ExpertSuggestion` se estavam definidos inline e agora sem uso.

- [ ] **Step 3: Deletar o ExpertsModal órfão (não é montado por ninguém)**

```bash
git rm -r frontend/src/components/ExpertsModal
```

- [ ] **Step 4: Verificar import backend + build front**

Run: `cd backend && python -c "import src.main"` e `cd frontend && npm run build`
Expected: ambos OK. (Se o build acusar import de `ExpertsModal` em algum barrel, remover a linha do barrel.)

- [ ] **Step 5: Commit**

```bash
git add -A backend/src/routes/experts.py frontend/src/components
git commit -m "chore(experts): remove endpoints do modal orfao + ExpertsModal (nao montado)"
```

### Task C4.2: Remover routes/projects.py e seus imports

**Files:**
- Delete: `backend/src/routes/projects.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: Remover os usos de projects_router e get_project_manager em main.py**

Em `backend/src/main.py`, remover:
- `from .routes.projects import get_project_manager` (linha 24).
- `from .routes.projects import router as projects_router` (linha 27).
- `app.include_router(projects_router)` (linha 102).
(Manter `projects_registry_router` — linha 28/103.)

- [ ] **Step 2: Deletar o arquivo**

```bash
git rm backend/src/routes/projects.py
```

- [ ] **Step 3: Verificar import backend**

Run: `cd backend && python -c "import src.main"`
Expected: sem erro (nada mais importa de `routes.projects`; `experts.py` já perdeu o import em C4.1).

- [ ] **Step 4: Commit**

```bash
git add backend/src/main.py
git commit -m "chore(projects): remove routes/projects.py legado (callers do front mortos)"
```

### Task C4.3: Remover project_manager, database_manager, project_history e get_history_db

**Files:**
- Delete: `backend/src/project_manager.py`
- Delete: `backend/src/database_manager.py`
- Delete: `backend/src/models/project_history.py`
- Modify: `backend/src/database.py`
- Delete: `backend/tests/test_project_manager.py` (se existir)

- [ ] **Step 1: Remover get_history_db de database.py**

Em `backend/src/database.py`, apagar a função `get_history_db` inteira (linhas ~73-87) e seu import local `from .database_manager import db_manager`. Manter `Base`, `engine`, `async_session_maker`, `get_session`, `get_db`, `create_tables`, e o `_set_sqlite_pragma` próprio de database.py.

- [ ] **Step 2: Deletar os arquivos do modelo antigo**

```bash
git rm backend/src/project_manager.py backend/src/database_manager.py backend/src/models/project_history.py
git rm backend/tests/test_project_manager.py 2>/dev/null || true
```

- [ ] **Step 3: Verificar import backend**

Run: `cd backend && python -c "import src.main"`
Expected: sem erro. (Todos os imports de `database_manager`/`ProjectHistory`/`project_manager` eram locais dentro de funções agora removidas; se sobrar algum, o import de `main` acusa — grepar e remover.)

- [ ] **Step 4: Grep de confirmação**

Run: `cd backend && grep -rIl "database_manager\|ProjectHistory\|project_manager\|import ProjectManager" src/ || echo "limpo"`
Expected: `limpo` (ou só referências textuais em `src/migrations/*.py` de scripts standalone — não bloqueiam boot).

- [ ] **Step 5: Commit**

```bash
git add backend/src/database.py
git commit -m "chore(legacy): remove project_manager/database_manager/project_history + get_history_db"
```

### Task C4.4: Remover o ActiveProject

**Files:**
- Delete: `backend/src/models/project.py`
- Modify: `backend/src/models/__init__.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: main.py — remover o helper e o import de ActiveProject**

Em `backend/src/main.py`, remover:
- `from .models.project import ActiveProject  # noqa: F401` (linha ~43).
- O helper `get_active_project` inteiro (linhas ~192-197) — nada mais o chama após C1.

- [ ] **Step 2: models/__init__.py — desregistrar ActiveProject**

Remover `from .project import ActiveProject` (linha 7) e `"ActiveProject"` do `__all__` (linha 14).

- [ ] **Step 3: Deletar o model**

```bash
git rm backend/src/models/project.py
```

- [ ] **Step 4: Verificar import + grep**

Run: `cd backend && python -c "import src.main" && grep -rIl "ActiveProject\|active_project" src/ || echo "limpo"`
Expected: import OK; grep `limpo` (ou só o SQL legado `migrations/010_add_metrics_tables.sql` — arquivo histórico, não executado no boot; opcionalmente ajustar o comentário/DDL, mas não bloqueia).

- [ ] **Step 5: Commit**

```bash
git add backend/src/main.py backend/src/models/__init__.py
git commit -m "chore(legacy): remove ActiveProject (worktree/git ja usam o registry)"
```

### Task C4.5: Suíte verde + validação de fluxo

**Files:**
- Modify: testes que ainda referenciem `ActiveProject`/legado (ajustar/remover)

- [ ] **Step 1: Rodar a suíte inteira**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS. Se algum teste falhar por referenciar `ActiveProject`/`ProjectManager`/`database_manager`/rotas removidas, ajustar ou remover o teste (eram do modelo antigo).

- [ ] **Step 2: Boot + smoke de fluxo**

Subir o backend + front. Verificar (com **apenas `maiconsaraiva/spike-loop-test`**): o app sobe sem erro; o seletor de projeto funciona; o dropdown de branches do AddCard lista branches do projeto selecionado; rodar um card no pipeline (worktree é criado pelo runner, que já usava o registry) e o chat responde no cwd do projeto. Nenhuma tela quebrou pela remoção do legado.

- [ ] **Step 3: Grep final de sanidade**

Run: `cd backend && grep -rIl "ActiveProject\|database_manager\|project_manager\|ProjectHistory" src/ || echo "backend limpo"`
Expected: `backend limpo` (fora de `src/migrations/*.py` histórico).

- [ ] **Step 4: Commit (se houve ajuste de teste)**

```bash
git add backend/tests
git commit -m "test(legacy): remove/ajusta testes do subsistema legado removido"
```

---

## Fim do Plano 2

Ao concluir C1–C4: o subsistema legado de "projeto ativo" está removido, worktree/git e experts-triage são escopados pelo `Project` do registry, e o FK do metrics aponta pra `projects.id`. Antes de promover: `cd backend && python -m pytest tests/ -v` (verde) + `cd frontend && npm run build` (verde) + smoke de boot/fluxo.
