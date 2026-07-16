# Painel — Fase 2a: Fundação de Dados (banco único + config) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans. Steps usam checkbox (`- [ ]`). **Esta é a Fase 2a** (fundação de dados) da Fase 2 (ver `docs/specs/2026-07-02-panel-fase2-multiprojeto-workflow-design.md`). A **Fase 2b** (rotas project-scoped + seletor + board dirigido por config no frontend) ganha plano próprio depois.

**Goal:** Consolidar num **banco único SQLite** (no repo, via `.env`), com tabelas `Project` (registro) e `Workflow` (config semeada), e `project_id` na tabela `cards` — sem quebrar o boot e com testes da lógica nova.

**Architecture:** Fundação de dados, TDD com `pytest`. O `database.py` já tem engine único a partir de `DATABASE_URL`; basta parar de usar o `db_manager` (multi-arquivo) no caminho de sessão. Adiciona `Project`/`Workflow` (globais) e `project_id` em `cards` (raiz tenant); execuções/logs escopam via card. Migração **lean sem Alembic**: `create_all` para tabelas novas + ALTER idempotente para colunas novas.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2 async / aiosqlite · pytest + pytest-asyncio · Windows + Git Bash. venv em `backend/venv/Scripts/`.

**Nota:** rodar tudo com o venv do backend: `cd backend && ./venv/Scripts/python.exe -m pytest ...`. O app sobe com `./venv/Scripts/python.exe -m src.main` (porta 3001, `ORCHESTRATOR_ENABLED=false` no `.env`).

---

## Task 1: Ferramentas de teste + banco único

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Modify: `backend/src/config/settings.py`
- Modify: `backend/src/database.py:53-66` (`get_session`)
- Modify: `.gitignore`
- Test: `backend/tests/test_single_engine.py`

- [ ] **Step 1: Adicionar pytest ao requirements (dev)**

Em `backend/requirements.txt`, acrescentar ao final:
```
pytest>=8.0.0
pytest-asyncio>=0.23.0
```
Instalar: `cd backend && ./venv/Scripts/python.exe -m pip install -q pytest pytest-asyncio`.

- [ ] **Step 2: Config do pytest-asyncio**

Criar `backend/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 3: Apontar `DATABASE_URL` default pro repo**

Em `backend/src/config/settings.py`, trocar a linha do `database_url` para o arquivo do orquestrador:
```python
    database_url: str = "sqlite+aiosqlite:///./orchestrator.db"
```
(O `.env` pode sobrescrever com `DATABASE_URL`. Ao rodar `python -m src.main` a partir de `backend/`, o arquivo nasce em `backend/orchestrator.db`.)

- [ ] **Step 4: Gitignore do banco**

Em `.gitignore` (raiz), acrescentar:
```
backend/orchestrator.db
backend/orchestrator.db-wal
backend/orchestrator.db-shm
```

- [ ] **Step 5: Escrever o teste do engine único (falha primeiro)**

Criar `backend/tests/test_single_engine.py`:
```python
import pytest
from src.database import get_session, async_session_maker


def test_get_session_returns_the_single_maker():
    # get_session deve devolver SEMPRE o async_session_maker unico,
    # sem depender do db_manager multi-arquivo (removido no caminho de sessao).
    assert get_session() is async_session_maker
```

- [ ] **Step 6: Rodar o teste — deve FALHAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_single_engine.py -v`
Esperado: FAIL (hoje `get_session` tenta `db_manager.get_current_session()` primeiro).

- [ ] **Step 7: Simplificar `get_session` (engine único)**

Em `backend/src/database.py`, substituir `get_session` (linhas 53-66) por:
```python
def get_session():
    """Session factory unica (banco unico via DATABASE_URL)."""
    return async_session_maker
```
(Não altere `get_db`/`get_history_db` nesta task. `db_manager` continua existindo mas fora do caminho de sessão — a remoção completa é da Fase 2b.)

- [ ] **Step 8: Rodar o teste — deve PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_single_engine.py -v`
Esperado: PASS.

- [ ] **Step 9: Boot sanity + commit**

Subir e checar health: `./venv/Scripts/python.exe -m src.main` (outro terminal: `curl -s localhost:3001/health`). Parar o servidor.
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent
git add backend/requirements.txt backend/pytest.ini backend/src/config/settings.py backend/src/database.py .gitignore backend/tests/test_single_engine.py
git commit -m "feat(db): banco unico via DATABASE_URL; get_session usa engine unico + pytest"
```

---

## Task 2: Registro de projetos (tabela `Project`)

**Files:**
- Create: `backend/src/models/project_registry.py`
- Modify: `backend/src/main.py:49` (importar o novo model para registrar no metadata)
- Test: `backend/tests/test_project_registry.py`

- [ ] **Step 1: Escrever o teste (falha primeiro)**

Criar `backend/tests/test_project_registry.py`:
```python
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.project_registry import Project


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_project_defaults(session):
    p = Project(id=str(uuid.uuid4()), name="GMS Web", path="/repos/gms")
    session.add(p)
    await session.commit()
    got = (await session.execute(select(Project))).scalar_one()
    assert got.rules_file == "AGENTS.md"
    assert got.base_branch == "main"
    assert got.favorite is False
    assert got.workflow_id is None
```

- [ ] **Step 2: Rodar — deve FALHAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_project_registry.py -v`
Esperado: FAIL com `ModuleNotFoundError: src.models.project_registry`.

- [ ] **Step 3: Criar o model `Project`**

Criar `backend/src/models/project_registry.py`:
```python
"""Registro (catalogo) de projetos-alvo. Tabela global (sem project_id)."""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Project(Base):
    """Projeto registrado no orquestrador (um repo-alvo)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    remote: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rules_file: Mapped[str] = mapped_column(String(120), nullable=False, default="AGENTS.md")
    validate_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name}, path={self.path})>"
```

- [ ] **Step 4: Registrar o model no boot**

Em `backend/src/main.py`, logo após a linha 49 (`from .models.project import ActiveProject  # noqa: F401`), adicionar:
```python
from .models.project_registry import Project  # noqa: F401
```

- [ ] **Step 5: Rodar — deve PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_project_registry.py -v`
Esperado: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/models/project_registry.py backend/src/main.py backend/tests/test_project_registry.py
git commit -m "feat(project): tabela Project (registro de projetos-alvo)"
```

---

## Task 3: Workflow como config (tabela + seed do workflow dev)

**Files:**
- Create: `backend/src/models/workflow.py`
- Create: `backend/src/services/workflow_seed.py`
- Modify: `backend/src/main.py` (import do model + chamada do seed no lifespan)
- Test: `backend/tests/test_workflow_seed.py`

- [ ] **Step 1: Escrever o teste (falha primeiro)**

Criar `backend/tests/test_workflow_seed.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.workflow import Workflow
from src.services.workflow_seed import seed_dev_workflow, DEV_WORKFLOW_ID


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_seed_creates_dev_workflow(maker):
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        wf = (await session_get(s)).scalar_one()
    assert wf.id == DEV_WORKFLOW_ID
    keys = [c["key"] for c in wf.columns]
    assert keys == ["backlog", "plan", "implement", "review",
                    "validate_ci", "ready_to_merge", "done", "paused"]
    # transicao do fix-loop existe
    assert "implement" in wf.transitions["review"]


async def test_seed_is_idempotent(maker):
    async with maker() as s:
        await seed_dev_workflow(s)
    async with maker() as s:
        await seed_dev_workflow(s)  # nao duplica
    async with maker() as s:
        count = len((await select_all(s)).scalars().all())
    assert count == 1


# helpers
from sqlalchemy import select as _select
async def session_get(s):
    return await s.execute(_select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID))
async def select_all(s):
    return await s.execute(_select(Workflow))
```

- [ ] **Step 2: Rodar — deve FALHAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_seed.py -v`
Esperado: FAIL (`ModuleNotFoundError: src.models.workflow`).

- [ ] **Step 3: Criar o model `Workflow`**

Criar `backend/src/models/workflow.py`:
```python
"""Workflow como config (colunas + transicoes). Tabela global."""

from datetime import datetime
from typing import Any
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Workflow(Base):
    """Definicao de workflow: colunas (com agente/provider/model) + transicoes."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # columns: list[{key,label,order,agentKey|None,provider,model|None,isPausedState,isTerminal}]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # transitions: {fromKey: [toKey, ...]}
    transitions: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Workflow(id={self.id}, name={self.name})>"
```

- [ ] **Step 4: Criar o seed do workflow dev**

Criar `backend/src/services/workflow_seed.py`:
```python
"""Semeia o workflow 'dev' default (idempotente)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.workflow import Workflow

DEV_WORKFLOW_ID = "dev"

# Coluna: key, label, agentKey (None = manual/backend), provider, model, flags
DEV_COLUMNS = [
    {"key": "backlog", "label": "Backlog", "order": 0, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "plan", "label": "Plan", "order": 1, "agentKey": "plan",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "implement", "label": "Implement", "order": 2, "agentKey": "implement",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "review", "label": "Review", "order": 3, "agentKey": "review",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "validate_ci", "label": "Validate/CI", "order": 4, "agentKey": "validate-ci",
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "ready_to_merge", "label": "Ready to merge", "order": 5, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": False},
    {"key": "done", "label": "Done", "order": 6, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": False, "isTerminal": True},
    {"key": "paused", "label": "Paused", "order": 7, "agentKey": None,
     "provider": "claude", "model": None, "isPausedState": True, "isTerminal": False},
]

# Caminho feliz + fix-loop (review->implement) + pausa a partir de qualquer etapa ativa.
DEV_TRANSITIONS = {
    "backlog": ["plan", "paused"],
    "plan": ["implement", "paused"],
    "implement": ["review", "paused"],
    "review": ["validate_ci", "implement", "paused"],
    "validate_ci": ["ready_to_merge", "implement", "paused"],
    "ready_to_merge": ["done", "paused"],
    "done": [],
    "paused": ["plan", "implement", "review", "validate_ci", "ready_to_merge"],
}


async def seed_dev_workflow(session: AsyncSession) -> None:
    """Cria o workflow dev se ainda nao existir (idempotente)."""
    existing = await session.execute(
        select(Workflow).where(Workflow.id == DEV_WORKFLOW_ID)
    )
    if existing.scalar_one_or_none() is not None:
        return
    session.add(Workflow(
        id=DEV_WORKFLOW_ID,
        name="Desenvolvimento (DevKit)",
        columns=DEV_COLUMNS,
        transitions=DEV_TRANSITIONS,
    ))
    await session.commit()
```

- [ ] **Step 5: Registrar model + chamar o seed no boot**

Em `backend/src/main.py`:
- Após a linha do import do `Project` (Task 2 Step 4), adicionar:
  ```python
  from .models.workflow import Workflow  # noqa: F401
  ```
- No `lifespan`, logo após `await create_tables()` (linha ~73) e o print de sucesso, adicionar:
  ```python
  from .services.workflow_seed import seed_dev_workflow
  from .database import async_session_maker
  async with async_session_maker() as _s:
      await seed_dev_workflow(_s)
  print("[Server] Dev workflow seeded")
  ```

- [ ] **Step 6: Rodar — deve PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_seed.py -v`
Esperado: PASS (2 testes).

- [ ] **Step 7: Boot sanity + commit**

Subir o app; confirmar no log `Dev workflow seeded` e nenhum erro. Parar.
```bash
git add backend/src/models/workflow.py backend/src/services/workflow_seed.py backend/src/main.py backend/tests/test_workflow_seed.py
git commit -m "feat(workflow): tabela Workflow + seed do workflow dev (7 colunas + paused)"
```

---

## Task 4: `project_id` na tabela `cards` + migração leve

**Files:**
- Modify: `backend/src/models/card.py` (novo campo `project_id`)
- Create: `backend/src/services/light_migrations.py`
- Modify: `backend/src/main.py` (chamar a migração leve no lifespan)
- Test: `backend/tests/test_card_project_scope.py`

- [ ] **Step 1: Escrever o teste (falha primeiro)**

Criar `backend/tests/test_card_project_scope.py`:
```python
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from src.database import Base
from src.models.card import Card


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_cards_isolated_by_project_id(maker):
    async with maker() as s:
        s.add(Card(id=str(uuid.uuid4()), title="A", project_id="proj-A"))
        s.add(Card(id=str(uuid.uuid4()), title="B", project_id="proj-B"))
        await s.commit()
    async with maker() as s:
        rows = (await s.execute(
            select(Card).where(Card.project_id == "proj-A")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "A"
```

- [ ] **Step 2: Rodar — deve FALHAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_card_project_scope.py -v`
Esperado: FAIL (`Card` não tem `project_id`).

- [ ] **Step 3: Adicionar `project_id` ao model `Card`**

Em `backend/src/models/card.py`, logo após a linha 19 (`column_id: ...`), adicionar:
```python
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
```
(Nullable nesta fase — cards legados podem não ter projeto ainda; a Fase 2b torna obrigatório na criação via rota project-scoped.)

- [ ] **Step 4: Rodar — deve PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_card_project_scope.py -v`
Esperado: PASS.

- [ ] **Step 5: Migração leve para DB existente (ALTER idempotente)**

Criar `backend/src/services/light_migrations.py`:
```python
"""Migracoes leves idempotentes (sem Alembic) para DBs ja criados.

Adiciona colunas novas via ALTER TABLE quando faltarem. Seguro rodar sempre:
consulta o PRAGMA e so aplica o que falta. YAGNI ate precisarmos de Alembic.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# (tabela, coluna, definicao SQL) a garantir
_COLUMNS = [
    ("cards", "project_id", "VARCHAR(36)"),
]


async def run_light_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, column, ddl in _COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {r[1] for r in rows}  # r[1] = nome da coluna
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
```

- [ ] **Step 6: Escrever o teste da migração leve (falha primeiro)**

Adicionar em `backend/tests/test_card_project_scope.py`:
```python
from sqlalchemy import text
from src.services.light_migrations import run_light_migrations


async def test_light_migration_adds_missing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # cria a tabela cards SEM project_id (simula DB legado)
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE cards (id VARCHAR(36) PRIMARY KEY, title VARCHAR(255), column_id VARCHAR(20))"
        ))
    await run_light_migrations(engine)
    await run_light_migrations(engine)  # idempotente: rodar 2x nao quebra
    async with engine.begin() as conn:
        cols = {r[1] for r in await conn.execute(text("PRAGMA table_info(cards)"))}
    assert "project_id" in cols
    await engine.dispose()
```

- [ ] **Step 7: Rodar os testes da task — devem PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_card_project_scope.py -v`
Esperado: PASS (2 testes).

- [ ] **Step 8: Chamar a migração leve no boot**

Em `backend/src/main.py`, no `lifespan`, logo após `await create_tables()` e ANTES do seed (Task 3 Step 5), adicionar:
```python
from .services.light_migrations import run_light_migrations
from .database import engine as _engine
await run_light_migrations(_engine)
```

- [ ] **Step 9: Boot sanity + commit**

Subir com um `backend/orchestrator.db` já existente (o criado nas tasks anteriores) e confirmar que sobe sem erro e o `cards.project_id` existe. Parar.
```bash
git add backend/src/models/card.py backend/src/services/light_migrations.py backend/src/main.py backend/tests/test_card_project_scope.py
git commit -m "feat(cards): project_id em cards + migracao leve idempotente (ALTER)"
```

---

## Task 5: Validação de transição derivada do config

**Files:**
- Create: `backend/src/services/workflow_rules.py`
- Test: `backend/tests/test_workflow_rules.py`

- [ ] **Step 1: Escrever o teste (falha primeiro)**

Criar `backend/tests/test_workflow_rules.py`:
```python
import pytest
from src.services.workflow_rules import is_valid_transition
from src.services.workflow_seed import DEV_TRANSITIONS


def test_valid_transition_from_config():
    assert is_valid_transition(DEV_TRANSITIONS, "implement", "review") is True


def test_fix_loop_transition_allowed():
    assert is_valid_transition(DEV_TRANSITIONS, "review", "implement") is True


def test_invalid_transition_rejected():
    assert is_valid_transition(DEV_TRANSITIONS, "backlog", "done") is False


def test_unknown_column_rejected():
    assert is_valid_transition(DEV_TRANSITIONS, "inexistente", "done") is False
```

- [ ] **Step 2: Rodar — deve FALHAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_rules.py -v`
Esperado: FAIL (`ModuleNotFoundError: src.services.workflow_rules`).

- [ ] **Step 3: Implementar a validação (a partir do config, não hardcoded)**

Criar `backend/src/services/workflow_rules.py`:
```python
"""Regras de movimentacao de card derivadas do config do Workflow."""


def is_valid_transition(transitions: dict[str, list[str]], src: str, dst: str) -> bool:
    """True se `dst` esta na lista de destinos permitidos de `src` no config."""
    return dst in transitions.get(src, [])
```

- [ ] **Step 4: Rodar — deve PASSAR**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_workflow_rules.py -v`
Esperado: PASS (4 testes).

- [ ] **Step 5: Rodar a bateria toda da Fase 2a + commit**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v`
Esperado: todos os testes novos PASS (e os pré-existentes não regridem).
```bash
git add backend/src/services/workflow_rules.py backend/tests/test_workflow_rules.py
git commit -m "feat(workflow): validacao de transicao derivada do config"
```

---

## Self-Review (preenchido)

**Cobertura do escopo (spec Fase 2, parte de dados):** banco único no repo/`.env` → Task 1; `Project` registry → Task 2; `Workflow` como config + seed dev (7 colunas + paused) → Task 3; `project_id` tenant-scoped + migração → Task 4; validação de transição do config → Task 5. **Fora desta 2a (vão pra 2b):** rotas `/api/projects/{projectId}/...`, remoção do `database_manager`/`ActiveProject`, repositórios filtrando por `project_id`, seletor no frontend, board dirigido por config, model picker, consolidação de dados legados multi-arquivo. ✓

**Placeholders:** nenhum TBD/TODO; todo passo de código traz o código real e o comando com resultado esperado. A estratégia de migração ficou decidida (lean sem Alembic, ALTER idempotente).

**Consistência de tipos/nomes:** `DEV_WORKFLOW_ID="dev"`, `DEV_COLUMNS`/`DEV_TRANSITIONS`, `seed_dev_workflow`, `is_valid_transition`, `run_light_migrations`, `Project`, `Workflow`, `Card.project_id` usados de forma idêntica entre tasks e testes. As chaves de coluna (`backlog/plan/implement/review/validate_ci/ready_to_merge/done/paused`) batem entre seed, transitions e o teste de ordem.

## Notas para a Fase 2b (não implementar aqui)

- Rotas tenant viram `/api/projects/{projectId}/...`; remover `get_active_project()` global e o `database_manager` (usos em `database.py:get_history_db`, `project_manager.py`, `routes/projects.py`).
- `CardRepository` passa a exigir/filtrar `project_id`; criação de card define `project_id` da rota.
- Frontend: `ProjectSelector`, board renderiza colunas do `Workflow` (unificar `types/index.ts` + `card_repository.py` + `schemas/card.py`), model picker por coluna.
- Reconciliar `ColumnId` (`schemas/card.py`) e `ALLOWED_TRANSITIONS` (`card_repository.py`) com o config; mapear colunas antigas dos cards (`test→review`, `completed→done`).
- Runner (Fase 3): lote de logs (buffer ~250ms) pra mitigar escrita concorrente no SQLite.
