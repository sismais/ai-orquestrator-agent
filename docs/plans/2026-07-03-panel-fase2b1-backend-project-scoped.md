# Painel — Fase 2b-1: Backend project-scoped (API de registro + workflow + cards) — Plano

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps usam checkbox (`- [ ]`). Parte **2b-1** (backend durável, aditivo) da Fase 2 (ver `docs/specs/2026-07-02-panel-fase2-multiprojeto-workflow-design.md`). O **2b-2** (frontend: seletor, board dirigido por config, `projectId` nas chamadas, e validação de move por config) vem depois. **Adiado p/ Fase 3:** remover `database_manager`/ativo-global de vez, escopar `execute-*`, remover `ActiveProject`.

**Goal:** Expor no backend, de forma **aditiva e sem quebrar o que existe**: (1) API de registro de projetos (CRUD sobre a tabela `Project`), (2) API de workflow (`GET` da config), (3) cards filtrando por `project_id` opcional.

**Architecture:** TDD com pytest. Tudo aditivo: rotas novas sob `/api/registry/*` e `/api/workflows/*`; `CardRepository` ganha `project_id` opcional (None = comportamento atual). Nada de remover rotas/serviços legados nesta parte.

**Tech Stack:** FastAPI / SQLAlchemy 2 async / pytest. venv em `backend/venv/Scripts/`. Rodar: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v`.

---

## Task 1: ProjectRepository (CRUD sobre a tabela `Project`)

**Files:**
- Create: `backend/src/repositories/project_repository.py`
- Test: `backend/tests/test_project_repository.py`

- [ ] **Step 1: Teste (falha primeiro)** — Criar `backend/tests/test_project_repository.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.database import Base
from src.repositories.project_repository import ProjectRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_and_list(session):
    repo = ProjectRepository(session)
    p = await repo.create(name="GMS Web", path="/repos/gms", workflow_id="dev")
    await session.commit()
    assert p.id and p.workflow_id == "dev" and p.base_branch == "main"
    all_ = await repo.list()
    assert len(all_) == 1 and all_[0].name == "GMS Web"


async def test_get_by_path_is_unique_upsert(session):
    repo = ProjectRepository(session)
    await repo.create(name="A", path="/repos/x")
    await session.commit()
    dup = await repo.get_by_path("/repos/x")
    assert dup is not None and dup.name == "A"


async def test_update_and_delete(session):
    repo = ProjectRepository(session)
    p = await repo.create(name="A", path="/repos/y")
    await session.commit()
    await repo.update(p.id, {"favorite": True, "name": "A2"})
    await session.commit()
    got = await repo.get_by_id(p.id)
    assert got.favorite is True and got.name == "A2"
    assert await repo.delete(p.id) is True
    await session.commit()
    assert await repo.get_by_id(p.id) is None
```

- [ ] **Step 2: Rodar — FALHA.** `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_project_repository.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar** — Criar `backend/src/repositories/project_repository.py`:
```python
"""Repository para o registro de projetos (tabela Project)."""

from uuid import uuid4
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.project_registry import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Project]:
        result = await self.session.execute(
            select(Project).order_by(Project.favorite.desc(), Project.last_opened_at.desc().nullslast())
        )
        return list(result.scalars().all())

    async def get_by_id(self, project_id: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.path == path))
        return result.scalar_one_or_none()

    async def create(self, name: str, path: str, workflow_id: str | None = "dev",
                     remote: str | None = None, rules_file: str = "AGENTS.md",
                     validate_command: str | None = None, base_branch: str = "main") -> Project:
        project = Project(
            id=str(uuid4()), name=name, path=path, remote=remote,
            rules_file=rules_file, validate_command=validate_command,
            base_branch=base_branch, workflow_id=workflow_id,
        )
        self.session.add(project)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def update(self, project_id: str, fields: dict[str, Any]) -> Optional[Project]:
        project = await self.get_by_id(project_id)
        if not project:
            return None
        allowed = {"name", "remote", "rules_file", "validate_command",
                   "base_branch", "workflow_id", "favorite", "last_opened_at"}
        for key, value in fields.items():
            if key in allowed:
                setattr(project, key, value)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: str) -> bool:
        project = await self.get_by_id(project_id)
        if not project:
            return False
        await self.session.delete(project)
        await self.session.flush()
        return True
```

- [ ] **Step 4: Rodar — PASSA.** Mesmo comando. Esperado: 3 passed.

- [ ] **Step 5: Commit.**
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent
git add backend/src/repositories/project_repository.py backend/tests/test_project_repository.py
git commit -m "feat(project): ProjectRepository (CRUD do registro de projetos)"
```

---

## Task 2: Rotas do registro de projetos (`/api/registry/projects`)

**Files:**
- Create: `backend/src/routes/projects_registry.py`
- Modify: `backend/src/main.py` (registrar o router)
- Test: `backend/tests/test_projects_registry_routes.py`

- [ ] **Step 1: Teste (falha primeiro)** — Criar `backend/tests/test_projects_registry_routes.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import src.database as database
from src.database import Base


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # aponta o get_db do app para o engine de teste
    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(database, "get_session", lambda: maker)
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_register_list_and_delete_project(client):
    # cria
    r = await client.post("/api/registry/projects", json={"name": "GMS Web", "path": "/repos/gms"})
    assert r.status_code == 201, r.text
    pid = r.json()["project"]["id"]
    # lista
    r = await client.get("/api/registry/projects")
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json()["projects"])
    # deleta
    r = await client.delete(f"/api/registry/projects/{pid}")
    assert r.status_code == 200
```

- [ ] **Step 2: Rodar — FALHA.** `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_projects_registry_routes.py -v` (instale httpx se faltar: `./venv/Scripts/python.exe -m pip install -q httpx`). Esperado: 404/erro (rota inexistente).

- [ ] **Step 3: Implementar as rotas** — Criar `backend/src/routes/projects_registry.py`:
```python
"""Rotas do registro de projetos (catalogo, tabela Project). Aditivo — nao
substitui as rotas legadas /api/projects (load/current/recent)."""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..repositories.project_repository import ProjectRepository

router = APIRouter(prefix="/api/registry/projects", tags=["projects-registry"])


class ProjectCreateBody(BaseModel):
    name: str
    path: str
    remote: Optional[str] = None
    rules_file: str = Field("AGENTS.md", alias="rulesFile")
    validate_command: Optional[str] = Field(None, alias="validateCommand")
    base_branch: str = Field("main", alias="baseBranch")
    workflow_id: Optional[str] = Field("dev", alias="workflowId")

    class Config:
        populate_by_name = True


class ProjectPatchBody(BaseModel):
    name: Optional[str] = None
    remote: Optional[str] = None
    rules_file: Optional[str] = Field(None, alias="rulesFile")
    validate_command: Optional[str] = Field(None, alias="validateCommand")
    base_branch: Optional[str] = Field(None, alias="baseBranch")
    workflow_id: Optional[str] = Field(None, alias="workflowId")
    favorite: Optional[bool] = None

    class Config:
        populate_by_name = True


def _to_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "path": p.path, "remote": p.remote,
        "rulesFile": p.rules_file, "validateCommand": p.validate_command,
        "baseBranch": p.base_branch, "workflowId": p.workflow_id,
        "favorite": p.favorite,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
        "lastOpenedAt": p.last_opened_at.isoformat() if p.last_opened_at else None,
    }


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    return {"projects": [_to_dict(p) for p in await repo.list()]}


@router.post("", status_code=201)
async def create_project(body: ProjectCreateBody, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    if await repo.get_by_path(body.path):
        raise HTTPException(status_code=409, detail="Project with this path already registered")
    p = await repo.create(
        name=body.name, path=body.path, remote=body.remote, rules_file=body.rules_file,
        validate_command=body.validate_command, base_branch=body.base_branch,
        workflow_id=body.workflow_id,
    )
    await db.commit()
    return {"project": _to_dict(p)}


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    p = await repo.get_by_id(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": _to_dict(p)}


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatchBody, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    p = await repo.update(project_id, body.model_dump(exclude_unset=True, by_alias=False))
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return {"project": _to_dict(p)}


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    repo = ProjectRepository(db)
    if not await repo.delete(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return {"success": True}
```

- [ ] **Step 4: Registrar o router** — Em `backend/src/main.py`, junto dos outros `app.include_router(...)` (após `app.include_router(projects_router)`), adicionar:
```python
from .routes.projects_registry import router as projects_registry_router
app.include_router(projects_registry_router)
```
(Coloque o `import` junto dos demais imports de rotas no topo e o `include_router` junto dos outros.)

- [ ] **Step 5: Rodar — PASSA.** Esperado: 1 passed. Verifique também `import src.main` OK.

- [ ] **Step 6: Commit.**
```bash
git add backend/src/routes/projects_registry.py backend/src/main.py backend/tests/test_projects_registry_routes.py
git commit -m "feat(project): rotas /api/registry/projects (CRUD do registro)"
```

---

## Task 3: API de workflow (`GET /api/workflows/{id}`)

**Files:**
- Create: `backend/src/routes/workflows.py`
- Modify: `backend/src/main.py` (registrar o router)
- Test: `backend/tests/test_workflows_routes.py`

- [ ] **Step 1: Teste (falha primeiro)** — Criar `backend/tests/test_workflows_routes.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import src.database as database
from src.database import Base
from src.services.workflow_seed import seed_dev_workflow


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await seed_dev_workflow(s)
    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(database, "get_session", lambda: maker)
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_get_dev_workflow(client):
    r = await client.get("/api/workflows/dev")
    assert r.status_code == 200, r.text
    wf = r.json()["workflow"]
    keys = [c["key"] for c in wf["columns"]]
    assert keys == ["backlog", "plan", "implement", "review",
                    "validate_ci", "ready_to_merge", "done", "paused"]
    assert "implement" in wf["transitions"]["review"]


async def test_get_unknown_workflow_404(client):
    r = await client.get("/api/workflows/inexistente")
    assert r.status_code == 404
```

- [ ] **Step 2: Rodar — FALHA.** `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflows_routes.py -v`.

- [ ] **Step 3: Implementar** — Criar `backend/src/routes/workflows.py`:
```python
"""Rotas de leitura da config de workflow (tabela Workflow)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.workflow import Workflow

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": {
        "id": wf.id, "name": wf.name,
        "columns": wf.columns, "transitions": wf.transitions,
    }}
```

- [ ] **Step 4: Registrar o router** — Em `backend/src/main.py`, junto dos outros:
```python
from .routes.workflows import router as workflows_router
app.include_router(workflows_router)
```

- [ ] **Step 5: Rodar — PASSA.** Esperado: 2 passed. `import src.main` OK.

- [ ] **Step 6: Commit.**
```bash
git add backend/src/routes/workflows.py backend/src/main.py backend/tests/test_workflows_routes.py
git commit -m "feat(workflow): rota GET /api/workflows/{id} (config para o board)"
```

---

## Task 4: Cards filtrando por `project_id` (aditivo, back-compat)

**Files:**
- Modify: `backend/src/schemas/card.py` (`CardCreate` ganha `project_id` opcional)
- Modify: `backend/src/repositories/card_repository.py` (`get_all`/`create` aceitam `project_id`)
- Modify: `backend/src/routes/cards.py` (`GET` aceita `?project_id=`; `create` propaga)
- Test: `backend/tests/test_cards_project_scope_repo.py`

- [ ] **Step 1: Teste (falha primeiro)** — Criar `backend/tests/test_cards_project_scope_repo.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.database import Base
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_with_project_id_and_filtered_list(session):
    repo = CardRepository(session)
    await repo.create(CardCreate(title="A"), project_id="proj-A")
    await repo.create(CardCreate(title="B"), project_id="proj-B")
    await session.commit()
    only_a = await repo.get_all(project_id="proj-A")
    assert len(only_a) == 1 and only_a[0].title == "A"
    all_cards = await repo.get_all()  # sem filtro = todos (back-compat)
    assert len(all_cards) == 2
```

- [ ] **Step 2: Rodar — FALHA.** `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_cards_project_scope_repo.py -v` (falha: `create` não aceita `project_id`).

- [ ] **Step 3: `CardCreate` ganha `project_id`** — Em `backend/src/schemas/card.py`, na classe `CardCreate` (após o campo `dependencies`, antes do `class Config`), adicionar:
```python
    project_id: Optional[str] = Field(None, alias="projectId")
```

- [ ] **Step 4: `CardRepository` aceita `project_id`** — Em `backend/src/repositories/card_repository.py`:
  - No `get_all`, trocar a assinatura e a query:
    ```python
    async def get_all(self, project_id: Optional[str] = None, include_archived: bool = True) -> list[Card]:
        """Get all cards ordered by creation date, optionally scoped by project."""
        query = select(Card)
        if project_id is not None:
            query = query.where(Card.project_id == project_id)
        query = query.order_by(Card.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())
    ```
  - No `create`, adicionar o parâmetro e setar o campo:
    ```python
    async def create(self, card_data: CardCreate, project_id: Optional[str] = None) -> Card:
    ```
    e no `Card(...)` acrescentar:
    ```python
            project_id=project_id if project_id is not None else getattr(card_data, "project_id", None),
    ```

- [ ] **Step 5: Rodar — PASSA.** Esperado: 1 passed.

- [ ] **Step 6: Rotas de card propagam `project_id`** — Em `backend/src/routes/cards.py`:
  - `GET`: trocar a assinatura e a chamada:
    ```python
    @router.get("", response_model=CardsListResponse)
    async def get_all_cards(project_id: str | None = Query(default=None, alias="projectId"), db: AsyncSession = Depends(get_db)):
        repo = CardRepository(db)
        exec_repo = ExecutionRepository(db)
        cards = await repo.get_all(project_id=project_id)
    ```
    (`Query` já está importado de `fastapi` no topo do arquivo.)
  - `POST` create: trocar a chamada `card = await repo.create(card_data)` por:
    ```python
        card = await repo.create(card_data, project_id=card_data.project_id)
    ```

- [ ] **Step 7: Rodar a bateria toda + `import src.main` + commit.**
```bash
cd backend && ./venv/Scripts/python.exe -c "import src.main" && ./venv/Scripts/python.exe -m pytest tests/test_cards_project_scope_repo.py tests/test_project_repository.py tests/test_projects_registry_routes.py tests/test_workflows_routes.py -v
cd /d/Sismais/Fontes/ai-orquestrator-agent
git add backend/src/schemas/card.py backend/src/repositories/card_repository.py backend/src/routes/cards.py backend/tests/test_cards_project_scope_repo.py
git commit -m "feat(cards): filtro/criacao por project_id (aditivo, back-compat)"
```

---

## Self-Review (preenchido)

**Cobertura (parte durável do project-scoping backend):** registro de projetos (Task 1-2), config de workflow p/ o board (Task 3), cards por project_id (Task 4). **Fora (2b-2/Fase 3):** frontend/seletor, `projectId` no `create` via UI, validação de move por config + cutover de colunas, remoção de `database_manager`/`ActiveProject`, escopo dos `execute-*`.

**Aditivo/back-compat:** rotas novas em prefixos próprios (`/api/registry/*`, `/api/workflows/*`); `get_all(project_id=None)` mantém o comportamento atual quando sem filtro; `CardCreate.project_id` é opcional. Nenhuma rota/serviço legado removido.

**Consistência:** `Project`/`Workflow` (tabelas da Fase 2a) reutilizados; chaves de coluna do workflow batem com o seed; `ProjectRepository` usado tanto no teste quanto nas rotas.

**Testes de rota** usam `httpx.AsyncClient` + `ASGITransport` com `monkeypatch` do `async_session_maker`/`get_session` para um engine em memória (não tocam o `orchestrator.db` real).

## Notas p/ 2b-2 (frontend) e Fase 3
- Board renderiza colunas de `GET /api/workflows/dev`; validação de move no backend deve passar a usar `is_valid_transition(wf.transitions, ...)` **junto** com o cutover de colunas (mismatch se separado).
- `card_repository.move` tem efeitos colaterais por id literal (`done`→migrations em `.claude/database.db` [morto no modelo banco-único → remover], diff em `review/done`, `completed_at` em `done`) — reconciliar no cutover de colunas.
- Seletor: reusar `ProjectSwitcher`, trocar fonte p/ `/api/registry/projects`, remover `window.location.reload()`; `App.tsx` re-fetch por efeito de `currentProject` (hoje é mount-once).
