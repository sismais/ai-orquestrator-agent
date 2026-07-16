# Projeto = escopo do app (feature) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subir o seletor de projeto pro nível do app (escopa Kanban + Chat), atualizar os modelos LLM (opus-4.8/sonnet-5/haiku-4.5 + fable-5 desabilitado, −gemini, 1M em opus/sonnet) ligando o modelo-por-etapa no pipeline, e tornar o chat project-scoped + persistido em DB.

**Architecture:** Backend FastAPI + SQLAlchemy async (SQLite, banco único via `create_all`, sem Alembic — migrações leves idempotentes). Frontend React 18 + Vite + TS + CSS Modules (SEM infra de teste — validação de front = `npm run build` (tsc) + browser). Backend com pytest + pytest-asyncio (`asyncio_mode=auto`), fixtures SQLite in-memory por teste.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, claude-agent-sdk, pytest; React 18.2, Vite 5, TypeScript 5.3, lucide-react.

**Escopo deste plano:** Fases A, D, B. A Fase C (remoção do subsistema legado ActiveProject/database_manager/…) está no plano separado `2026-07-07-remocao-subsistema-legado.md` e depende deste.

**Ordem recomendada:** A → D → B. Cada fase termina num estado committável e verde. `agent_chat.py` é tocado por D (remove ramo Gemini + atualiza `model_mapping`) e por B (adiciona `cwd`); D primeiro deixa B mexendo só no ramo Claude.

**Repo:** `D:/Sismais/Fontes/ai-orquestrator-agent` (todos os caminhos abaixo são relativos a essa raiz).

---

## FASE A — Seletor de projeto app-level (frontend)

Move o `<ProjectSelectorRegistry>` do `KanbanPage` para o `TopNav` (via `WorkspaceLayout`), escopando todos os módulos. O estado `currentProjectId` já vive no `App.tsx` — não muda de lugar; só passa a fluir também para o layout.

### Task A1: WorkspaceLayout repassa projeto ao TopNav

**Files:**
- Modify: `frontend/src/layouts/WorkspaceLayout.tsx`

- [ ] **Step 1: Adicionar props de projeto e repassar ao TopNav**

Substituir o arquivo inteiro (24 linhas) por:

```tsx
import { ReactNode } from 'react';
import TopNav from '../components/Navigation/TopNav';
import styles from './WorkspaceLayout.module.css';

export type ModuleType = 'dashboard' | 'kanban' | 'chat' | 'settings';

interface WorkspaceLayoutProps {
  children: ReactNode;
  currentModule: ModuleType;
  onNavigate: (module: ModuleType) => void;
  currentProjectId: string | null;
  onProjectSwitch: (projectId: string) => void;
}

const WorkspaceLayout = ({ children, currentModule, onNavigate, currentProjectId, onProjectSwitch }: WorkspaceLayoutProps) => {
  return (
    <div className={styles.workspace}>
      <TopNav
        currentModule={currentModule}
        onNavigate={onNavigate}
        currentProjectId={currentProjectId}
        onProjectSwitch={onProjectSwitch}
      />
      <main className={styles.content}>
        {children}
      </main>
    </div>
  );
};

export default WorkspaceLayout;
```

- [ ] **Step 2: Verificar typecheck (vai falhar até A2/A3 — esperado)**

Run: `cd frontend && npm run build`
Expected: erro TS em `TopNav` (props novas ainda não existem) e em `App.tsx` (ainda não passa as props). Segue pra A2.

### Task A2: TopNav renderiza o seletor dentro do navRight

**Files:**
- Modify: `frontend/src/components/Navigation/TopNav.tsx`

- [ ] **Step 1: Importar o seletor e receber as props**

No topo do arquivo, após o import de styles (linha 2), adicionar:
```tsx
import { ProjectSelectorRegistry } from '../ProjectSelectorRegistry/ProjectSelectorRegistry';
```

Trocar a interface de props (linhas 4-7) por:
```tsx
interface TopNavProps {
  currentModule: ModuleType;
  onNavigate: (module: ModuleType) => void;
  currentProjectId: string | null;
  onProjectSwitch: (projectId: string) => void;
}
```

Trocar a assinatura (linha 16) por:
```tsx
const TopNav = ({ currentModule, onNavigate, currentProjectId, onProjectSwitch }: TopNavProps) => {
```

- [ ] **Step 2: Renderizar o seletor como primeiro filho de `.navRight`**

No bloco `<div className={styles.navRight}>` (linha 40), inserir o seletor ANTES do primeiro `<button className={styles.iconBtn}>`:
```tsx
        <div className={styles.navRight}>
          <ProjectSelectorRegistry currentProjectId={currentProjectId} onSwitch={onProjectSwitch} />
          <button className={styles.iconBtn} title="Search — ⌘K">
```
(manter o restante do `navRight` — search/notif/avatar — inalterado)

- [ ] **Step 3: Verificar typecheck (ainda falha em App.tsx — esperado)**

Run: `cd frontend && npm run build`
Expected: erro TS restante só em `App.tsx` (não passa `currentProjectId`/`onProjectSwitch` ao `WorkspaceLayout`). Segue pra A3.

### Task A3: App passa o projeto ao WorkspaceLayout e KanbanPage para de renderizar o seletor

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/KanbanPage.tsx`

- [ ] **Step 1: App.tsx — passar as props ao WorkspaceLayout**

Localizar o `return` que renderiza `<WorkspaceLayout ...>` (por volta das linhas 717-722) e trocar por:
```tsx
  return (
    <WorkspaceLayout
      currentModule={currentView}
      onNavigate={handleNavigate}
      currentProjectId={currentProjectId}
      onProjectSwitch={setCurrentProjectId}
    >
      {renderView()}
      <div id="modal-root" />
    </WorkspaceLayout>
  );
```
(NÃO remover a passagem de `currentProjectId`/`onProjectIdSwitch` ao `KanbanPage` — o `AddCard` ainda precisa de `currentProjectId`.)

- [ ] **Step 2: KanbanPage.tsx — remover a renderização do seletor (manter o AddCard)**

Remover o import do seletor (linha 5):
```tsx
import { ProjectSelectorRegistry } from '../components/ProjectSelectorRegistry/ProjectSelectorRegistry';
```
No bloco `.projectActions` (linhas 65-71), remover só o `<ProjectSelectorRegistry ...>`, deixando o `AddCard`:
```tsx
        <div className={styles.projectActions}>
          <AddCard columnId="backlog" onAdd={onAddCard} projectId={currentProjectId} />
        </div>
```
(Manter as props `currentProjectId`/`onProjectIdSwitch` na interface e no destructuring do `KanbanPage` — `onProjectIdSwitch` pode ficar sem uso agora; se o tsc reclamar de var não usada, prefixar com `_` no destructuring: `onProjectIdSwitch: _onProjectIdSwitch`. Só fazer isso se o build acusar `noUnusedParameters`.)

- [ ] **Step 3: Verificar typecheck limpo**

Run: `cd frontend && npm run build`
Expected: PASS (tsc sem erros, build gera dist).

- [ ] **Step 4: Validação visual no browser**

Subir o app (backend + `npm run dev`), abrir `http://localhost:<porta>`. Verificar: o seletor de projeto aparece no topo (TopNav, à direita), trocar de projeto reflete no Kanban, e ao ir pra aba Chat o seletor continua visível (escopo app-level). Sem projeto selecionado, o board mostra vazio (comportamento atual preservado).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/layouts/WorkspaceLayout.tsx frontend/src/components/Navigation/TopNav.tsx frontend/src/App.tsx frontend/src/pages/KanbanPage.tsx
git commit -m "feat(ui): seletor de projeto app-level no TopNav (escopa kanban + chat)"
```

---

## FASE D — Modelos LLM atualizados + modelo-por-etapa no pipeline

Atualiza os modelos (opus-4.8/sonnet-5/haiku-4.5 + fable-5 desabilitado, −gemini, 1M em opus/sonnet), liga o modelo escolhido por etapa na execução do pipeline, e cria um único ponto de mapeamento alias→id do SDK compartilhado entre chat e pipeline.

**IDs do SDK (Claude Code CLI):** `opus-4.8 → claude-opus-4-8[1m]`, `sonnet-5 → claude-sonnet-5[1m]`, `haiku-4.5 → claude-haiku-4-5`, `fable-5 → claude-fable-5`. O `[1m]` é a variante de 1M de contexto (padrão desta sessão é `claude-opus-4-8[1m]`).

### Task D1: Módulo compartilhado de mapeamento alias→id do SDK

**Files:**
- Create: `backend/src/config/model_ids.py`
- Test: `backend/tests/test_model_ids.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_model_ids.py
from src.config.model_ids import resolve_model_id, ALIAS_TO_MODEL_ID


def test_resolve_known_aliases():
    assert resolve_model_id("opus-4.8") == "claude-opus-4-8[1m]"
    assert resolve_model_id("sonnet-5") == "claude-sonnet-5[1m]"
    assert resolve_model_id("haiku-4.5") == "claude-haiku-4-5"
    assert resolve_model_id("fable-5") == "claude-fable-5"


def test_resolve_legacy_aliases_remapped():
    # aliases antigos ainda resolvem (dados legados nos cards)
    assert resolve_model_id("opus-4.5") == "claude-opus-4-8[1m]"
    assert resolve_model_id("sonnet-4.5") == "claude-sonnet-5[1m]"


def test_resolve_unknown_falls_back_to_sonnet():
    assert resolve_model_id("nao-existe") == "claude-sonnet-5[1m]"
    assert resolve_model_id(None) == "claude-sonnet-5[1m]"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_model_ids.py -v`
Expected: FAIL (ModuleNotFoundError: src.config.model_ids)

- [ ] **Step 3: Implementar o módulo**

```python
# backend/src/config/model_ids.py
"""Mapa unico alias -> id real do modelo no Claude Code CLI/SDK.

Fonte de verdade compartilhada entre o chat (agent_chat) e o pipeline
(stage_runner/pipeline_service). O sufixo [1m] seleciona a variante de 1M de
contexto (opus 4.8 e sonnet 5 tem). haiku 4.5 e 200k (sem 1m). fable-5 fica
mapeado mas desabilitado nos pickers (beta).
"""
from typing import Optional

ALIAS_TO_MODEL_ID = {
    # atuais
    "opus-4.8": "claude-opus-4-8[1m]",
    "sonnet-5": "claude-sonnet-5[1m]",
    "haiku-4.5": "claude-haiku-4-5",
    "fable-5": "claude-fable-5",
    # legados remapeados (cards antigos)
    "opus-4.5": "claude-opus-4-8[1m]",
    "sonnet-4.5": "claude-sonnet-5[1m]",
}

_FALLBACK = "claude-sonnet-5[1m]"


def resolve_model_id(alias: Optional[str]) -> str:
    """Resolve um alias de UI para o id real do SDK. Desconhecido/None -> fallback."""
    if not alias:
        return _FALLBACK
    return ALIAS_TO_MODEL_ID.get(alias, _FALLBACK)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_model_ids.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add backend/src/config/model_ids.py backend/tests/test_model_ids.py
git commit -m "feat(models): modulo compartilhado alias->id do SDK (1m em opus/sonnet)"
```

### Task D2: Remover Gemini do chat (agent_chat + arquivos órfãos)

**Files:**
- Modify: `backend/src/agent_chat.py`
- Delete: `backend/src/gemini_agent.py`
- Delete: `backend/src/services/gemini_service.py`

- [ ] **Step 1: Remover o método `_stream_response_gemini` e o roteamento**

Em `backend/src/agent_chat.py`:
- Apagar o método `_stream_response_gemini` inteiro (linhas ~25-84).
- No `stream_response`, apagar o bloco de roteamento Gemini (linhas ~106-111):
```python
        # Check if it's a Gemini model
        if model.startswith("gemini"):
            print(f"[ClaudeAgentChat] Detected Gemini model, routing to _stream_response_gemini")
            async for chunk in self._stream_response_gemini(messages, model, system_prompt):
                yield chunk
            return
```

- [ ] **Step 2: Trocar o `model_mapping` por uso do módulo compartilhado**

Adicionar no topo do arquivo (junto aos imports):
```python
from .config.model_ids import resolve_model_id
```
Substituir o bloco `model_mapping` + `agent_model = ...` (linhas ~128-142) por:
```python
            agent_model = resolve_model_id(model)
```

- [ ] **Step 3: Deletar os arquivos Gemini**

```bash
git rm backend/src/gemini_agent.py backend/src/services/gemini_service.py
```

- [ ] **Step 4: Verificar boot (import) do backend**

Run: `cd backend && python -c "import src.main"`
Expected: sem ImportError (o backend importa `main` sem erro). Se algum outro arquivo importava `gemini_agent`/`gemini_service`, o erro aparece aqui — nesse caso, remover o import órfão (grep `gemini` em `backend/src`).

- [ ] **Step 5: Commit**

```bash
git add -A backend/src/agent_chat.py
git commit -m "refactor(chat): remove Gemini do chat; usa mapa alias->id compartilhado"
```

### Task D3: ModelType + pricing + defaults (backend)

**Files:**
- Modify: `backend/src/schemas/card.py`
- Modify: `backend/src/models/card.py`
- Modify: `backend/src/config/pricing.py`
- Modify: `backend/src/migrations/002_add_model_config_to_cards.sql`
- Modify: `backend/src/execution.py`
- Modify: `backend/src/schemas/chat.py`

> Preços por 1M tokens (input, output), do skill claude-api: opus-4.8 5/25 · sonnet-5 3/15 · haiku-4.5 1/5 · fable-5 10/50.

- [ ] **Step 1: schemas/card.py — ModelType + defaults**

Trocar `ModelType` (linhas 32-35) por:
```python
ModelType = Literal[
    "opus-4.8", "sonnet-5", "haiku-4.5",  # Claude
    "fable-5",  # Claude (beta, desabilitado nos pickers)
]
```
Trocar os defaults do `CardBase` (linhas 84-87) de `"opus-4.5"` para `"opus-4.8"` (4 campos: model_plan/implement/test/review).

- [ ] **Step 2: models/card.py — defaults ORM**

Trocar os 4 `default="opus-4.5"` (linhas 22-25) por `default="opus-4.8"`. Manter `String(20)` (os aliases novos cabem).

- [ ] **Step 3: config/pricing.py — MODEL_PRICING**

Trocar o dict (linhas 7-16) por:
```python
MODEL_PRICING: Dict[str, Tuple[Decimal, Decimal]] = {
    "opus-4.8": (Decimal("5.00"), Decimal("25.00")),
    "sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "haiku-4.5": (Decimal("1.00"), Decimal("5.00")),
    "fable-5": (Decimal("10.00"), Decimal("50.00")),
}
```

- [ ] **Step 4: migrations/002 + execution.py + schemas/chat.py — defaults**

- `backend/src/migrations/002_add_model_config_to_cards.sql` (linhas 2-5): trocar `DEFAULT 'opus-4.5'` → `DEFAULT 'opus-4.8'` nos 4 ALTER.
- `backend/src/execution.py` (linhas 68,100,114,130): trocar `model: Optional[str] = "opus-4.5"` → `= "opus-4.8"`.
- `backend/src/schemas/chat.py` (linha 38): trocar default `"sonnet-4.5"` → `"sonnet-5"`.

- [ ] **Step 5: Verificar import + testes de pricing/card**

Run: `cd backend && python -c "import src.main" && python -m pytest tests/ -k "pricing or card_repository or model" -v`
Expected: import OK; testes de pricing/model passam. (Os de `card_repository` que fixam ids antigos vão falhar — corrigidos na Task D4.)

- [ ] **Step 6: Commit**

```bash
git add backend/src/schemas/card.py backend/src/models/card.py backend/src/config/pricing.py backend/src/migrations/002_add_model_config_to_cards.sql backend/src/execution.py backend/src/schemas/chat.py
git commit -m "feat(models): atualiza ModelType/pricing/defaults do backend (opus-4.8/sonnet-5/+fable-5/-gemini)"
```

### Task D4: Migração leve — remap de aliases antigos nos cards + defaults de chat

**Files:**
- Modify: `backend/src/services/light_migrations.py`
- Modify: `backend/src/agent_chat.py`
- Modify: `backend/src/routes/chat.py`
- Modify: `backend/src/services/chat_service.py`
- Test: `backend/tests/test_model_alias_migration.py`

- [ ] **Step 1: Escrever teste da migração (idempotente, roda 2x)**

```python
# backend/tests/test_model_alias_migration.py
import src.models  # noqa: F401  (registra models no Base.metadata)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.database import Base
from src.services.light_migrations import remap_legacy_model_aliases


async def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def test_remap_legacy_model_aliases_idempotent():
    engine = await _make_engine()
    # seed um card com aliases antigos
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO cards (id, title, column_id, model_plan, model_implement, model_test, model_review) "
            "VALUES ('c1', 't', 'backlog', 'opus-4.5', 'sonnet-4.5', 'opus-4.5', 'sonnet-4.5')"
        ))
    # roda 2x (idempotencia)
    await remap_legacy_model_aliases(engine)
    await remap_legacy_model_aliases(engine)
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT model_plan, model_implement, model_test, model_review FROM cards WHERE id='c1'"
        ))).first()
    assert row == ("opus-4.8", "sonnet-5", "opus-4.8", "sonnet-5")
    await engine.dispose()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_model_alias_migration.py -v`
Expected: FAIL (ImportError: remap_legacy_model_aliases não existe)

- [ ] **Step 3: Implementar a migração de remap**

Em `backend/src/services/light_migrations.py`, adicionar (no fim do arquivo, seguindo o padrão de `remap_legacy_columns`):
```python
# Remap de aliases de modelo legados -> aliases atuais (idempotente)
_MODEL_ALIAS_REMAP = {"opus-4.5": "opus-4.8", "sonnet-4.5": "sonnet-5"}
_MODEL_COLUMNS = ("model_plan", "model_implement", "model_test", "model_review")


async def remap_legacy_model_aliases(engine: AsyncEngine) -> None:
    """Remapeia aliases de modelo antigos nos cards para os atuais (idempotente)."""
    async with engine.begin() as conn:
        for col in _MODEL_COLUMNS:
            for old, new in _MODEL_ALIAS_REMAP.items():
                await conn.execute(
                    text(f"UPDATE cards SET {col} = :new WHERE {col} = :old"),
                    {"new": new, "old": old},
                )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_model_alias_migration.py -v`
Expected: PASS

- [ ] **Step 5: Chamar a migração no startup**

Em `backend/src/main.py`, no `lifespan` (junto às chamadas existentes `run_light_migrations`/`remap_legacy_columns`, ~linhas 62-68), adicionar:
```python
    from .services.light_migrations import remap_legacy_model_aliases
    await remap_legacy_model_aliases(_engine)
```

- [ ] **Step 6: Atualizar defaults `sonnet-4.5` → `sonnet-5` no chat (backend)**

- `backend/src/agent_chat.py`: default de `model` em `stream_response` (linha ~89, agora sem o ramo gemini) e onde houver `"sonnet-4.5"` (linhas ~203). Trocar por `"sonnet-5"`. Se houver dicts de sugestão de modelo por etapa (linhas ~257-272 do arquivo original) que citem `opus-4.5`/gemini, atualizar para os novos aliases ou remover se obsoletos.
- `backend/src/routes/chat.py` (linhas 107,136): `"sonnet-4.5"` → `"sonnet-5"`.
- `backend/src/services/chat_service.py` (linha 206): default `model: str = "sonnet-4.5"` → `"sonnet-5"`.

- [ ] **Step 7: Verificar import + testes**

Run: `cd backend && python -c "import src.main" && python -m pytest tests/test_model_alias_migration.py tests/test_model_ids.py -v`
Expected: import OK; testes verdes.

- [ ] **Step 8: Commit**

```bash
git add backend/src/services/light_migrations.py backend/src/main.py backend/src/agent_chat.py backend/src/routes/chat.py backend/src/services/chat_service.py backend/tests/test_model_alias_migration.py
git commit -m "feat(models): remap idempotente de aliases legados + chat default sonnet-5"
```

### Task D5: Corrigir testes backend que fixam ids de modelo antigos

**Files:**
- Modify: `backend/tests/test_card_repository.py`
- Modify: `backend/tests/test_move_by_config.py`

- [ ] **Step 1: Trocar os ids de modelo nos testes**

Em `backend/tests/test_card_repository.py` (linhas 49-52, 73-76, 86-89, 110-113, 127-130, 151-154, 188-191, 221-224, 244-247, 257-260) e `backend/tests/test_move_by_config.py` (linha 49): substituir `"opus-4.5"`→`"opus-4.8"`, `"sonnet-4.5"`→`"sonnet-5"`, `"haiku-4.5"` fica, e qualquer `"gemini-3-*"` → `"haiku-4.5"` (ou remover a asserção específica de gemini).

- [ ] **Step 2: Rodar a suíte backend inteira**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (verde). Se algum teste ainda referenciar gemini/aliases antigos, corrigir.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_card_repository.py backend/tests/test_move_by_config.py
git commit -m "test(models): atualiza ids de modelo nos testes de card/move"
```

### Task D6: Ligar o modelo-por-etapa no pipeline

**Files:**
- Modify: `backend/src/services/stage_runner.py`
- Modify: `backend/src/services/pipeline_service.py`
- Test: `backend/tests/test_pipeline_model_wiring.py`

- [ ] **Step 1: Teste — o pipeline passa o modelo da etapa ao stage_fn**

```python
# backend/tests/test_pipeline_model_wiring.py
import src.models  # noqa: F401
from src.services.pipeline_service import stage_model_for_column


def test_stage_model_for_column_maps_stage_to_card_field():
    class FakeCard:
        model_plan = "opus-4.8"
        model_implement = "sonnet-5"
        model_review = "haiku-4.5"
    card = FakeCard()
    assert stage_model_for_column("plan", card) == "opus-4.8"
    assert stage_model_for_column("implement", card) == "sonnet-5"
    assert stage_model_for_column("review", card) == "haiku-4.5"
    # coluna sem modelo por etapa -> None (usa default do CLI)
    assert stage_model_for_column("validate_ci", card) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_pipeline_model_wiring.py -v`
Expected: FAIL (ImportError: stage_model_for_column)

- [ ] **Step 3: stage_runner — aceitar e usar `model`**

Em `backend/src/services/stage_runner.py`, trocar a assinatura de `run_stage` (linhas 144-145) por:
```python
async def run_stage(stage_key: str, worktree: str, prompt: str, card_id: Optional[str] = None,
                    on_log=None, model: Optional[str] = None) -> StageResult:
```
No topo do arquivo, importar:
```python
from .config.model_ids import resolve_model_id
```
> Atenção ao caminho relativo: `stage_runner.py` está em `backend/src/services/`, então o import é `from ..config.model_ids import resolve_model_id`.

Na construção de `ClaudeAgentOptions` (linhas 152-158), adicionar `model=` só quando houver alias:
```python
    body, tools = load_stage_agent(stage_key)
    options_kwargs = dict(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": body},
        allowed_tools=tools,
        permission_mode="acceptEdits",
    )
    if model:
        options_kwargs["model"] = resolve_model_id(model)
    options = ClaudeAgentOptions(**options_kwargs)
```

- [ ] **Step 4: pipeline_service — mapear coluna→campo e passar o modelo**

Em `backend/src/services/pipeline_service.py`, adicionar a função helper (nível de módulo, perto do topo):
```python
_STAGE_MODEL_FIELD = {"plan": "model_plan", "implement": "model_implement", "review": "model_review"}


def stage_model_for_column(col: str, card) -> "str | None":
    """Alias do modelo escolhido para a etapa (coluna) corrente, ou None se a coluna nao executa agente por-modelo."""
    field = _STAGE_MODEL_FIELD.get(col)
    return getattr(card, field, None) if field else None
```
Nas chamadas ao `stage_fn` (linha 284 e a do fix-loop, linha 343), passar o modelo:
```python
            res = await stage_fn(col, worktree, prompt, card_id=card_id, on_log=log,
                                 model=stage_model_for_column(col, card))
```
```python
                    fix_res = await stage_fn("implement", worktree, fix_prompt, card_id=card_id, on_log=log,
                                             model=stage_model_for_column("implement", card))
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_pipeline_model_wiring.py -v`
Expected: PASS

- [ ] **Step 6: Verificar suíte backend inteira**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (verde)

- [ ] **Step 7: Commit**

```bash
git add backend/src/services/stage_runner.py backend/src/services/pipeline_service.py backend/tests/test_pipeline_model_wiring.py
git commit -m "feat(pipeline): liga o modelo-por-etapa (card.model_*) na execucao do stage"
```

### Task D7: ModelType + pricing + pickers (frontend)

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/constants/pricing.ts`
- Modify: `frontend/src/components/Chat/ModelSelector.tsx`
- Modify: `frontend/src/components/AddCardModal/AddCardModal.tsx`
- Modify: `frontend/src/components/ModelCard/ModelCard.module.css`
- Modify: `frontend/src/hooks/useDraft.ts`
- Modify: `frontend/src/hooks/useChat.ts`

- [ ] **Step 1: types/index.ts — ModelType + ModelProvider**

Trocar `ModelType` (linhas 18-20) por:
```ts
export type ModelType =
  | 'opus-4.8' | 'sonnet-5' | 'haiku-4.5'  // Claude
  | 'fable-5';  // Claude (beta, desabilitado)
```
Trocar `ModelProvider` (linha 26) por: `export type ModelProvider = 'anthropic';` (remove `'google'`).

- [ ] **Step 2: constants/pricing.ts — MODEL_PRICING (Record força consistência)**

Trocar o `MODEL_PRICING` (linhas 13-36) por:
```ts
export const MODEL_PRICING: Record<ModelType, ModelPricing> = {
  'opus-4.8': { inputPricePerMillion: 5.00, outputPricePerMillion: 25.00 },
  'sonnet-5': { inputPricePerMillion: 3.00, outputPricePerMillion: 15.00 },
  'haiku-4.5': { inputPricePerMillion: 1.00, outputPricePerMillion: 5.00 },
  'fable-5': { inputPricePerMillion: 10.00, outputPricePerMillion: 50.00 },
};
```

- [ ] **Step 3: ModelSelector.tsx (chat) — AVAILABLE_MODELS**

Trocar a lista `AVAILABLE_MODELS` (linhas 9-70) pelos 4 modelos Claude, todos `provider: 'anthropic'`, `fable-5` com flag de desabilitado. Usar `maxTokens: 1000000` para opus-4.8/sonnet-5/fable-5 e `200000` para haiku-4.5. Exemplo de entrada:
```tsx
  {
    id: 'opus-4.8', name: 'Claude Opus 4.8', displayName: 'Opus 4.8',
    provider: 'anthropic', maxTokens: 1000000, description: 'Mais capaz',
    performance: 'powerful', badge: 'Most Capable', icon: '...', accent: 'opus',
  },
  { id: 'sonnet-5', name: 'Claude Sonnet 5', displayName: 'Sonnet 5', provider: 'anthropic', maxTokens: 1000000, description: 'Equilíbrio', performance: 'balanced', badge: 'Best Value', icon: '...', accent: 'sonnet' },
  { id: 'haiku-4.5', name: 'Claude Haiku 4.5', displayName: 'Haiku 4.5', provider: 'anthropic', maxTokens: 200000, description: 'Rápido', performance: 'fastest', icon: '...', accent: 'haiku' },
  { id: 'fable-5', name: 'Claude Fable 5', displayName: 'Fable 5', provider: 'anthropic', maxTokens: 1000000, description: 'Beta (indisponível)', performance: 'powerful', badge: 'Beta', icon: '...', accent: 'fable', disabled: true },
```
Se o tipo `AIModel` (em `ModelSelector.types.ts`) não tiver `disabled?: boolean`, adicionar esse campo opcional lá, e no render do seletor desabilitar a opção quando `disabled` (ex.: `<option disabled>` ou botão `disabled`). Ajustar o `provider` do tipo `AIModel` para `'anthropic'` (remover `'openai'|'google'` se causar erro). Manter os `icon`/`accent` no estilo já usado (copiar ícones das entradas antigas Claude).

- [ ] **Step 4: AddCardModal.tsx — MODEL_CARDS**

Trocar `MODEL_CARDS` (linhas 31-77) pelos 4 cards Claude (opus-4.8/sonnet-5/haiku-4.5/fable-5), `provider: 'anthropic'`, accents `'opus'/'sonnet'/'haiku'/'fable'`, `fable-5` com `disabled: true` (adicionar o campo ao tipo `ModelCardData` se não existir, e no render marcar o card como desabilitado/não-selecionável). Trocar os defaults `'opus-4.5'` (linhas 109-112, 191-194) e o fallback de `getModelValue` (linha 382) para `'opus-4.8'`.

- [ ] **Step 5: ModelCard.module.css — accents**

Em `frontend/src/components/ModelCard/ModelCard.module.css`: remover os blocos `.gemini-pro`/`.gemini-flash` (linhas 256-274) e adicionar um accent `fable`:
```css
.modelCard.fable { --model-accent: 217, 70, 239; }
```
(manter `.opus`/`.sonnet`/`.haiku`.)

- [ ] **Step 6: useDraft.ts + useChat.ts — defaults**

- `frontend/src/hooks/useDraft.ts` (linhas 69-72): `'opus-4.5'` → `'opus-4.8'` (4 campos).
- `frontend/src/hooks/useChat.ts` (linha 20): `selectedModel: 'sonnet-4.5'` → `'sonnet-5'`.

- [ ] **Step 7: Verificar typecheck limpo**

Run: `cd frontend && npm run build`
Expected: PASS. (O `Record<ModelType, ...>` em pricing.ts e as listas garantem que nada ficou com id antigo/gemini.)

- [ ] **Step 8: Validação visual**

Abrir o AddCardModal (novo card) e o seletor do chat: 4 modelos Claude, `Fable 5` visível porém desabilitado, sem Gemini; cada card com sua cor (accent). Criar um card escolhendo modelos diferentes por etapa e conferir que salva.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/constants/pricing.ts frontend/src/components/Chat/ModelSelector.tsx frontend/src/components/Chat/ModelSelector.types.ts frontend/src/components/AddCardModal/AddCardModal.tsx frontend/src/components/ModelCard/ModelCard.module.css frontend/src/hooks/useDraft.ts frontend/src/hooks/useChat.ts
git commit -m "feat(models): atualiza ModelType/pricing/pickers do front (+fable disabled, -gemini)"
```

---

## FASE B — Chat project-scoped + persistido em DB (backend + frontend)

Persiste sessões/mensagens de chat em DB com `project_id`, escopa o contexto do Kanban ao projeto, e faz o cwd do agente vir do `Project.path` selecionado (sem `ActiveProject`). Depende da Fase D (agent_chat.py já sem Gemini).

### Task B1: Models de chat (ChatSession, ChatMessage)

**Files:**
- Create: `backend/src/models/chat.py`
- Modify: `backend/src/models/__init__.py`
- Test: `backend/tests/test_chat_models.py`

- [ ] **Step 1: Teste — as tabelas nascem no create_all e o vínculo com projeto existe**

```python
# backend/tests/test_chat_models.py
import src.models  # noqa: F401  (registra models no Base.metadata)
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from src.database import Base


async def test_chat_tables_created():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "chat_session" in tables
    assert "chat_message" in tables
    await engine.dispose()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_chat_models.py -v`
Expected: FAIL (tabelas não existem)

- [ ] **Step 3: Criar os models**

```python
# backend/src/models/chat.py
"""Models de chat: sessoes e mensagens, escopadas por projeto (registry)."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_session.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: Registrar em models/__init__.py**

Adicionar (após a linha `from .metrics import ...`):
```python
from .chat import ChatSession, ChatMessage
```
E incluir `"ChatSession", "ChatMessage"` no `__all__`.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_chat_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/models/chat.py backend/src/models/__init__.py backend/tests/test_chat_models.py
git commit -m "feat(chat): models ChatSession/ChatMessage escopados por projeto"
```

### Task B2: Repositório de chat

**Files:**
- Create: `backend/src/repositories/chat_repository.py`
- Test: `backend/tests/test_chat_repository.py`

- [ ] **Step 1: Teste (padrão in-memory, commit explícito)**

```python
# backend/tests/test_chat_repository.py
import src.models  # noqa: F401
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
from src.repositories.chat_repository import ChatRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed_project(session, pid="p1", path="/repo/x"):
    from src.models.project_registry import Project
    session.add(Project(id=pid, name="X", path=path))
    await session.commit()


async def test_create_and_list_sessions_scoped_by_project(session):
    await _seed_project(session, "p1", "/repo/a")
    await _seed_project(session, "p2", "/repo/b")
    repo = ChatRepository(session)
    s1 = await repo.create_session(project_id="p1", title="oi")
    await repo.create_session(project_id="p2", title="outro")
    await session.commit()
    got = await repo.list_sessions("p1")
    assert [s.id for s in got] == [s1.id]


async def test_add_and_get_messages(session):
    await _seed_project(session, "p1", "/repo/a")
    repo = ChatRepository(session)
    s = await repo.create_session(project_id="p1")
    await repo.add_message(s.id, role="user", content="oi", model="sonnet-5")
    await repo.add_message(s.id, role="assistant", content="ola", model="sonnet-5")
    await session.commit()
    msgs = await repo.get_messages(s.id)
    assert [(m.role, m.content) for m in msgs] == [("user", "oi"), ("assistant", "ola")]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_chat_repository.py -v`
Expected: FAIL (ImportError: ChatRepository)

- [ ] **Step 3: Implementar o repositório (padrão card_repository: flush, sem commit)**

```python
# backend/src/repositories/chat_repository.py
"""Repositorio de chat: sessoes e mensagens por projeto. Segue o padrao do
card_repository (flush sem commit; quem chama commita)."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat import ChatSession, ChatMessage


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self, project_id: str, title: Optional[str] = None) -> ChatSession:
        obj = ChatSession(project_id=project_id, title=title)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        res = await self.session.execute(select(ChatSession).where(ChatSession.id == session_id))
        return res.scalar_one_or_none()

    async def list_sessions(self, project_id: str) -> List[ChatSession]:
        res = await self.session.execute(
            select(ChatSession).where(ChatSession.project_id == project_id).order_by(ChatSession.updated_at.desc())
        )
        return list(res.scalars().all())

    async def add_message(self, session_id: str, role: str, content: str, model: Optional[str] = None) -> ChatMessage:
        obj = ChatMessage(session_id=session_id, role=role, content=content, model=model)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_messages(self, session_id: str) -> List[ChatMessage]:
        res = await self.session.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        )
        return list(res.scalars().all())

    async def delete_session(self, session_id: str) -> bool:
        obj = await self.get_session(session_id)
        if not obj:
            return False
        # apaga mensagens e a sessao
        for m in await self.get_messages(session_id):
            await self.session.delete(m)
        await self.session.delete(obj)
        await self.session.flush()
        return True
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_chat_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/repositories/chat_repository.py backend/tests/test_chat_repository.py
git commit -m "feat(chat): repositorio de sessoes/mensagens por projeto"
```

### Task B3: agent_chat.stream_response recebe cwd explícito (sem ActiveProject)

**Files:**
- Modify: `backend/src/agent_chat.py`
- Test: `backend/tests/test_agent_chat_cwd.py`

- [ ] **Step 1: Teste — cwd é usado sem consultar ActiveProject**

```python
# backend/tests/test_agent_chat_cwd.py
import inspect
from src.agent_chat import get_claude_agent


def test_stream_response_accepts_cwd_param():
    sig = inspect.signature(get_claude_agent().stream_response)
    assert "cwd" in sig.parameters


def test_agent_chat_source_has_no_active_project():
    import src.agent_chat as m
    src = inspect.getsource(m)
    assert "ActiveProject" not in src  # cwd vem por parametro, nao do ActiveProject
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_agent_chat_cwd.py -v`
Expected: FAIL (sem param cwd; ActiveProject ainda presente)

- [ ] **Step 3: Adicionar `cwd` e remover a consulta a ActiveProject (ramo Claude)**

Em `backend/src/agent_chat.py`:
- Trocar a assinatura de `stream_response` (agora, pós-D2, sem gemini):
```python
    async def stream_response(
        self,
        messages: list[dict],
        model: str = "sonnet-5",
        system_prompt: str | None = None,
        cwd: str | None = None,
    ) -> AsyncGenerator[str, None]:
```
- Remover o bloco que consulta `ActiveProject` para o cwd (linhas ~113-127 do original — o `try:` com `select(ActiveProject)...`) e substituir por:
```python
        from pathlib import Path
        resolved_cwd = Path(cwd) if cwd else Path.cwd()
```
- Trocar `cwd=cwd` na construção de `ClaudeAgentOptions` (linha ~166) por `cwd=resolved_cwd`.
- Remover imports agora órfãos de `ActiveProject`/`async_session_maker`/`select` que só serviam a esse bloco (conferir se são usados em outro ponto do arquivo antes de remover).

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_agent_chat_cwd.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/agent_chat.py backend/tests/test_agent_chat_cwd.py
git commit -m "refactor(chat): stream_response recebe cwd explicito (sem ActiveProject)"
```

### Task B4: chat_service persiste em DB, resolve cwd por projeto e escopa o contexto

**Files:**
- Modify: `backend/src/services/chat_service.py`
- Test: `backend/tests/test_chat_service_scoped.py`

- [ ] **Step 1: Teste — send_message persiste e resolve cwd do Project**

```python
# backend/tests/test_chat_service_scoped.py
import src.models  # noqa: F401
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
from src.models.project_registry import Project
from src.repositories.chat_repository import ChatRepository


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_send_message_persists_and_uses_project_cwd(maker, monkeypatch):
    import src.services.chat_service as cs
    monkeypatch.setattr(cs, "async_session_maker", maker)

    # projeto no registry
    async with maker() as s:
        s.add(Project(id="p1", name="X", path="/repo/x"))
        await s.commit()
        repo = ChatRepository(s)
        chat = await repo.create_session(project_id="p1")
        await s.commit()
        session_id = chat.id

    captured = {}

    async def fake_stream(messages, model, system_prompt, cwd):
        captured["cwd"] = cwd
        yield "ola"

    service = cs.ChatService()
    monkeypatch.setattr(service.claude_agent, "stream_response", fake_stream)

    chunks = [c async for c in service.send_message(session_id=session_id, message="oi", model="sonnet-5")]
    assert any(c.get("type") == "chunk" for c in chunks)
    assert captured["cwd"] == "/repo/x"

    # persistiu user + assistant
    async with maker() as s:
        msgs = await ChatRepository(s).get_messages(session_id)
    assert [m.role for m in msgs] == ["user", "assistant"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_chat_service_scoped.py -v`
Expected: FAIL (chat_service ainda usa dict em memória e não passa cwd)

- [ ] **Step 3: Reescrever o ChatService para persistir + escopar por projeto**

Reescrever `backend/src/services/chat_service.py` removendo o `self.sessions` dict e o ramo `_orchestrator_enabled`/goal_classifier. Estrutura nova (pontos-chave):

- `__init__`: manter `self.claude_agent = get_claude_agent()`; remover `self.sessions`, `self.goal_classifier`, `self._orchestrator_enabled`.
- Nova assinatura: `async def send_message(self, session_id: str, message: str, model: str = "sonnet-5")`.
- Dentro de `send_message`, abrir uma sessão de DB (`async with async_session_maker() as db:`), e:
  1. `repo = ChatRepository(db)`; `chat = await repo.get_session(session_id)`; se `None` → yield `{"type":"error", "error":"Sessão não encontrada", ...}` e `return`.
  2. Resolver o projeto: `from ..repositories.project_repository import ProjectRepository`; `project = await ProjectRepository(db).get_by_id(chat.project_id)`; `cwd = project.path if project else None`.
  3. Persistir a mensagem do user: `await repo.add_message(session_id, "user", message, model)`; `await db.commit()`.
  4. Montar `claude_messages` a partir de `await repo.get_messages(session_id)` (role+content).
  5. `system_prompt = await self.get_system_prompt(chat.project_id)` (ver Step 4 — contexto scoped).
  6. Stream: `async for chunk in self.claude_agent.stream_response(messages=claude_messages, model=model, system_prompt=system_prompt, cwd=cwd): assistant_content += chunk; yield {"type":"chunk","content":chunk,"messageId":...}`.
  7. Persistir assistant: `await repo.add_message(session_id, "assistant", assistant_content, model)`; `await db.commit()`; yield `{"type":"end","messageId":...}`.
  8. `except Exception` → yield `{"type":"error", ...}`.
- `create_session(project_id: str)` → cria via `ChatRepository` numa sessão DB e retorna `{"sessionId": chat.id, "createdAt": chat.created_at}`.
- `get_session(session_id)` → lê mensagens do DB e devolve `{"sessionId":..., "messages":[...]}`.
- `delete_session(session_id)` → `ChatRepository.delete_session` + commit.
- `list_sessions(project_id: str)` → `ChatRepository.list_sessions(project_id)`.
- Manter os helpers `_format_relative_time`/`_truncate`.

- [ ] **Step 4: Escopar o contexto do Kanban ao projeto**

Trocar `_get_kanban_context(self)` para `_get_kanban_context(self, project_id: str)` e usar `card_repo.get_all(project_id=project_id)` (o `CardRepository.get_all` já aceita `project_id`). E `get_system_prompt(self, project_id: str)` repassa o `project_id`.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_chat_service_scoped.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/chat_service.py backend/tests/test_chat_service_scoped.py
git commit -m "feat(chat): chat_service persiste em DB, cwd por projeto e contexto scoped"
```

### Task B5: Rotas de chat exigem projectId na criação e listam por projeto

**Files:**
- Modify: `backend/src/routes/chat.py`
- Modify: `backend/src/schemas/chat.py`
- Test: `backend/tests/test_chat_routes_scoped.py`

- [ ] **Step 1: Teste de rota (ASGI + monkeypatch do session_maker)**

```python
# backend/tests/test_chat_routes_scoped.py
import src.models  # noqa: F401
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database import Base
import src.database as database
from src.models.project_registry import Project


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_maker", maker)
    async with maker() as s:
        s.add(Project(id="p1", name="X", path="/repo/x"))
        await s.commit()
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_create_session_requires_project_and_lists_scoped(client):
    r = await client.post("/api/chat/sessions", json={"projectId": "p1"})
    assert r.status_code == 200
    sid = r.json()["sessionId"]

    r2 = await client.get("/api/chat/sessions", params={"projectId": "p1"})
    assert r2.status_code == 200
    assert sid in [s["sessionId"] for s in r2.json()["sessions"]]

    # outro projeto nao ve a sessao
    r3 = await client.get("/api/chat/sessions", params={"projectId": "p2"})
    assert sid not in [s["sessionId"] for s in r3.json().get("sessions", [])]


async def test_create_session_without_project_is_rejected(client):
    r = await client.post("/api/chat/sessions", json={})
    assert r.status_code == 422  # projectId obrigatorio
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_chat_routes_scoped.py -v`
Expected: FAIL (POST /sessions não aceita projectId; GET /sessions não filtra)

- [ ] **Step 3: Ajustar schemas/chat.py**

Adicionar um request body para criar sessão:
```python
class CreateSessionRequest(BaseModel):
    project_id: str = Field(alias="projectId")

    class Config:
        populate_by_name = True
```
(Manter `CreateSessionResponse`.)

- [ ] **Step 4: Ajustar routes/chat.py**

- `POST /sessions`: receber `body: CreateSessionRequest` e chamar `await chat_service.create_session(project_id=body.project_id)`.
- `GET /sessions`: receber `project_id: str` (query, alias por `projectId` — usar `Query(..., alias="projectId")`) e retornar `{"sessions": [{"sessionId": s.id, "title": s.title, "createdAt": s.created_at} for s in await chat_service.list_sessions(project_id)]}`.
- O WS `/ws/{session_id}` e o `send_message` continuam usando o `session_id`; o `project_id` é resolvido pela própria sessão dentro do `chat_service` (Task B4). Remover o default `"sonnet-4.5"` remanescente no payload do WS → `"sonnet-5"` (se ainda existir).

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_chat_routes_scoped.py -v`
Expected: PASS

- [ ] **Step 6: Suíte backend inteira**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/routes/chat.py backend/src/schemas/chat.py backend/tests/test_chat_routes_scoped.py
git commit -m "feat(chat): rotas exigem projectId ao criar sessao e listam por projeto"
```

### Task B6: Front do chat usa o projeto selecionado

**Files:**
- Modify: `frontend/src/hooks/useChat.ts`
- Modify: `frontend/src/api/chat.ts`
- Modify: `frontend/src/api/config.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: useChat recebe/usa projectId e cria sessão via REST antes de conectar o WS**

Em `frontend/src/hooks/useChat.ts`:
- Assinatura: `export function useChat(projectId: string | null) {`.
- Ao abrir o chat / iniciar sessão: se `projectId` for `null`, expor um estado de erro/empty ("Selecione um projeto") e NÃO conectar o WS. Se houver `projectId`, criar a sessão via `createChatSession(projectId)` (REST) e usar o `sessionId` retornado para o WS (em vez de gerar `uuidv4()` no cliente).
- Incluir `projectId` no payload do `send({...})` como fallback (`{ type:'message', content, model, projectId }`), embora o backend resolva pela sessão.
- Ao trocar de `projectId` (novo argumento muda): resetar a sessão (nova sessão do projeto novo), limpar mensagens.

- [ ] **Step 2: api/chat.ts — createChatSession recebe projectId**

```ts
export async function createChatSession(projectId: string): Promise<CreateSessionResponse> {
  const response = await fetch(`${API_URL}/api/chat/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ projectId }),
  });
  if (!response.ok) throw new Error('Falha ao criar sessão de chat');
  return response.json();
}
```
(Se `useChat` passar a consumir `chatApi.createSession`, ajustar o barrel `chatApi` de acordo.)

- [ ] **Step 3: App.tsx — passar currentProjectId ao useChat e ao ChatPage**

Trocar a instanciação do hook (linha ~75):
```tsx
  const { state: chatState, sendMessage, handleModelChange, createNewSession } = useChat(currentProjectId);
```
No `case 'chat'` (linhas ~685-696), passar `currentProjectId` ao `ChatPage` (para o empty state):
```tsx
      case 'chat':
        return (
          <ChatPage
            messages={chatState.session?.messages || []}
            isLoading={chatState.isLoading}
            error={chatState.error}
            onSendMessage={sendMessage}
            selectedModel={chatState.selectedModel}
            onModelChange={handleModelChange}
            onNewChat={createNewSession}
            currentProjectId={currentProjectId}
          />
        );
```

- [ ] **Step 4: ChatPage.tsx — empty state sem projeto**

Adicionar `currentProjectId: string | null` às props e, quando `null`, renderizar um estado "Selecione um projeto para conversar" no lugar da conversa (não chamar a API).

- [ ] **Step 5: Verificar typecheck**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 6: Smoke real (repo de teste)**

Com o backend rodando: no app, selecionar o projeto de testes (**usar apenas `maiconsaraiva/spike-loop-test`** — repo exclusivo de testes), abrir o Chat, mandar uma mensagem e ver o agente responder no cwd do projeto. Trocar de projeto → as conversas trocam. Reiniciar o backend → o histórico persiste (DB).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useChat.ts frontend/src/api/chat.ts frontend/src/api/config.ts frontend/src/App.tsx frontend/src/pages/ChatPage.tsx
git commit -m "feat(chat): front usa o projeto selecionado (sessao por projeto, empty state sem projeto)"
```

---

## Fim do Plano 1

Ao concluir A + D + B: o seletor escopa o app, os modelos estão atualizados com modelo-por-etapa ligado, e o chat é project-scoped/persistido — e o chat/pipeline não dependem mais do `ActiveProject` (pré-requisito do Plano 2). Rodar a bateria antes de promover: `cd backend && python -m pytest tests/ -v` e `cd frontend && npm run build`.
