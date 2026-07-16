# Painel — Fase 1: Fundação & De-risk — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans. Steps usam checkbox (`- [ ]`). **Esta é a Fase 1 de 4** (ver `docs/specs/2026-06-17-ai-orquestrador-panel-design.md`). Fases 2–4 (multi-projeto+workflow-config, runner no backend, board) ganham plano próprio depois.

**Goal:** Deixar o fork rodando enxuto localmente, com o DevKit migrado pra `devkit/`, o **spike de skill-loading no SDK confirmado empiricamente** (dentro de uma worktree), rebrand + LICENSE, e um mapa do código pras próximas fases.

**Architecture:** Não há net-new de produto aqui — é fundação. Rodar → migrar DevKit → **provar o SDK carregando nossa skill numa worktree** (o único risco empírico) → cortar gordura → rebrand → mapear. Verificação é por **boot/execução**, não unit-TDD (fase exploratória).

**Tech Stack:** Python 3.9+ / FastAPI / venv · Node 18+ / Vite · `claude-agent-sdk` (Python) · Windows + Git Bash.

**Nota Windows:** venv ativa em `backend/venv/Scripts/activate` (não `bin/`). O Makefile assume Linux (`bin/activate`); no Git Bash use `. venv/Scripts/activate` ou chame `backend/venv/Scripts/python.exe` direto. `make` pode não existir no Windows — rode os comandos manualmente.

---

## Task 1: Subir o fork localmente (baseline)

**Objetivo:** backend em `:3001` e board em `:5173` no ar. (Porta 3001 vem do Makefile + do proxy do Vite; ignore o `8000` do `docs/CONFIGURATION.md` — é drift.)

- [ ] **Step 1: Pré-requisitos** — confirmar `python --version` (≥3.9), `node --version` (≥18), `git --version`, e Claude Code CLI instalado **e logado** (`~/.claude/.credentials.json` presente).

**Auth (decisão):** o `claude-agent-sdk` roda o Claude Code CLI por baixo. Sem `ANTHROPIC_API_KEY` no ambiente, ele usa o **login do CLI** — aqui a **assinatura Max** já logada (`subscriptionType: max`, scope `user:inference`). Então **`ANTHROPIC_API_KEY` é opcional**: default = assinatura Max; setar a chave só se quiser forçar a API (CI/carga pesada, onde os termos pedem API key). O fork **não** exige a chave (`settings.py` não tem campo de key da Anthropic). Confirmação empírica no spike da Task 3.

- [ ] **Step 2: Backend — venv + deps**
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent/backend
python -m venv venv
. venv/Scripts/activate      # Windows/Git Bash
pip install -r requirements.txt
```
Esperado: instala fastapi, `claude-agent-sdk`, sqlalchemy, aiosqlite, qdrant-client, sentence-transformers, google-generativeai. (qdrant/sentence-transformers/gemini serão cortados na Task 4 — por ora instala tudo pra subir.)

- [ ] **Step 3: `backend/.env`** — copiar do exemplo e setar porta:
```bash
cp .env.example .env 2>/dev/null || true
```
Editar `backend/.env`, garantindo (note: **sem `ANTHROPIC_API_KEY`** — usa a assinatura Max do CLI; ver Step 1):
```env
PORT=3001
DATABASE_URL=sqlite+aiosqlite:///./auth.db
STORE_DB_IN_PROJECT=true
AUTO_MIGRATE_LEGACY_DB=true
SECRET_KEY=dev-secret-troque-depois
```

- [ ] **Step 4: Frontend — deps + env**
```bash
cd ../frontend
npm install
printf 'VITE_API_URL=http://localhost:3001\nVITE_WS_URL=ws://localhost:3001\n' > .env
```

- [ ] **Step 5: Subir o backend e tratar o Qdrant no boot**

Run (Git Bash, na raiz do backend com venv ativo):
```bash
cd ../backend && . venv/Scripts/activate && python -m src.main
```
Esperado provável: **falha/erro tentando conectar no Qdrant** (o `orchestrator_service`/`memory_service` sobem em `src/main.py` `_run_orchestrator` e usam Qdrant via Docker :6333). Como vamos cortar o Qdrant na Task 4, aqui basta **desligar temporariamente o boot do orchestrator** para subir sem Docker:
- Em `backend/src/main.py`, comente a linha que agenda `_run_orchestrator` (o `asyncio.create_task(...)` do orchestrator, ~linha 97) e qualquer init de `qdrant_service`/`memory_service` no startup.
Rode de novo `python -m src.main`. Esperado: uvicorn sobe em `:3001` sem erro de conexão.

- [ ] **Step 6: Verificar**
```bash
curl -s http://localhost:3001/health && echo OK
```
Em outro terminal:
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent/frontend && npm run dev
```
Abrir `http://localhost:5173` — o board carrega. Anotar qualquer erro no console.

- [ ] **Step 7: Commit**
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent
git add backend/src/main.py
git commit -m "chore(fork): sobe local sem Qdrant (desliga orchestrator no boot)"
```
(Os `.env` e `venv/` não entram — confirme que estão no `.gitignore`.)

---

## Task 2: Migrar os agentes do DevKit para `devkit/`

**Objetivo:** trazer as skills/comandos do DevKit (do repo de plugins) pra `devkit/.claude/`, prontos pro spike e pras fases seguintes.

- [ ] **Step 1: Copiar skills, agents e commands**
```bash
SRC=/d/Sismais/Fontes/sismais-ai-plugins-workspace/sismais-ai-plugins-private/plugins
DST=/d/Sismais/Fontes/ai-orquestrator-agent/devkit/.claude
mkdir -p "$DST/skills" "$DST/agents" "$DST/commands"
cp -r "$SRC/sismais-dev/skills/"* "$DST/skills/"
cp -r "$SRC/sismais-dev/agents/"* "$DST/agents/"
cp -r "$SRC/sismais-dev/commands/"* "$DST/commands/"
cp -r "$SRC/sismais-dev-loop/agents/"* "$DST/agents/"
cp -r "$SRC/sismais-dev-loop/commands/"* "$DST/commands/"
cp -r "$SRC/sismais-dev-loop/skills/"* "$DST/skills/"
ls -R "$DST" | head -40
```
Esperado: `devkit/.claude/skills/{sismais-dev,sismais-dev-loop}/SKILL.md`, `agents/sismais-dev-*.md`, `commands/sismais-dev*.md`. (O estado/orquestração — `run-state.mjs`, `loop-state.mjs`, o loop `SKILL.md` orquestrador — **não** migram: serão substituídos pelo backend, conforme o design. Copiamos só os **agentes de etapa**.)

- [ ] **Step 2: Nota de origem** — criar `devkit/README.md` curto explicando que é a camada de agentes do DevKit (migrada do marketplace privado), invocada pelo orquestrador via SDK.

- [ ] **Step 3: Commit**
```bash
git add devkit/
git commit -m "feat(devkit): migra agentes de etapa do DevKit para devkit/.claude"
```

---

## Task 3: Spike — carregar uma skill do DevKit no SDK dentro de uma worktree (DE-RISK)

**Objetivo:** provar empiricamente que `claude-agent-sdk` reconhece nossa skill/comando quando `cwd` é uma **git worktree** (onde `.git` é *arquivo*, não pasta — a borda que quebrou o Gemini do autor). Resolve o único risco aberto.

**Files:**
- Create: `spike/skill_loading_spike.py` (descartável)

- [ ] **Step 1: Disponibilizar a skill (abordagem user-scope — menor delta)**
```bash
mkdir -p ~/.claude/skills ~/.claude/commands
cp -r /d/Sismais/Fontes/ai-orquestrator-agent/devkit/.claude/skills/* ~/.claude/skills/
cp -r /d/Sismais/Fontes/ai-orquestrator-agent/devkit/.claude/commands/* ~/.claude/commands/
```

- [ ] **Step 2: Criar uma worktree de teste de um repo-alvo** (ex.: gms-mobile)
```bash
cd /d/Sismais/Fontes/gms-mobile
git worktree add /d/Sismais/Fontes/_spike-wt -b spike-skill-loading
```

- [ ] **Step 3: Escrever o spike** — `spike/skill_loading_spike.py`:
```python
import asyncio, os
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    worktree = os.environ["SPIKE_WORKTREE"]
    options = ClaudeAgentOptions(
        cwd=worktree,
        setting_sources=["user", "project"],
        allowed_tools=["Skill", "Read", "Glob", "Grep"],
        permission_mode="acceptEdits",
    )
    prompt = "/sismais-dev-fix spike: apenas confirme, em uma linha, que a skill/comando sismais-dev foi carregada e reconhecida. Nao edite arquivos."
    async for message in query(prompt=prompt, options=options):
        name = type(message).__name__
        print("MSG", name, getattr(message, "result", "")[:200] if hasattr(message, "result") else "")

asyncio.run(main())
```

- [ ] **Step 4: Rodar o spike**
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent/backend && . venv/Scripts/activate
SPIKE_WORKTREE=/d/Sismais/Fontes/_spike-wt python ../spike/skill_loading_spike.py
```
Esperado (sucesso): o modelo reconhece o comando/skill (executa a instrução, sem dizer "comando desconhecido"). Se o `init`/logs listarem `sismais-dev*` nos slash_commands, melhor ainda.

- [ ] **Step 5: Se falhar dentro da worktree** (a borda `.git`-arquivo) — testar o **plano B**: copiar `devkit/.claude/` pra dentro da worktree e usar `setting_sources=["project"]`:
```bash
cp -r /d/Sismais/Fontes/ai-orquestrator-agent/devkit/.claude /d/Sismais/Fontes/_spike-wt/
```
Ajustar o spike (`setting_sources=["project"]`) e rodar de novo. Registrar qual abordagem funcionou.

- [ ] **Step 6: Documentar o resultado** — criar `docs/notes/2026-06-17-spike-skill-loading.md` com: abordagem vencedora (user-scope × worktree-copy), o comando que funcionou, e a decisão pro backend (como o runner vai disponibilizar as skills por run).

- [ ] **Step 7: Limpar a worktree de teste + commit**
```bash
cd /d/Sismais/Fontes/gms-mobile && git worktree remove /d/Sismais/Fontes/_spike-wt --force; git branch -D spike-skill-loading
cd /d/Sismais/Fontes/ai-orquestrator-agent && git add spike/ docs/notes/ && git commit -m "spike(sdk): confirma carregamento de skill do DevKit em worktree"
```

---

## Task 4: Cortar a gordura

**Objetivo:** remover o que sai no v1 (Qdrant, `/live`, Gemini, lixo) e garantir que o app ainda sobe.

> **Execução (2026-06-17):** feitos só os cortes **seguros** — arquivos-lixo, `docker-compose.yml`,
> e `sentence-transformers` (torch) do manifesto. **Live/votação, Orchestrator autônomo e Gemini
> foram ADIADOS para a Fase 3** (decisão do usuário): acoplam ao núcleo que a Fase 3 reescreve
> (`agent.py:525`→`live_broadcast_service`; `chat_service`→`orchestrator`; Gemini interleaved no
> `agent.py`). Ficam inertes até lá (`ORCHESTRATOR_ENABLED=false`; Gemini não ofertado).
> Pontos de acoplamento e arquivos catalogados em `docs/notes/2026-06-17-fork-code-map.md`.

- [ ] **Step 1: Qdrant + embeddings**
- Remover `docker-compose.yml` (só sobe o Qdrant).
- Remover `backend/src/services/qdrant_service.py`, `memory_service.py` e imports/usos deles (inclusive no `orchestrator_service.py`, que já desligamos no boot — pode remover o arquivo inteiro nesta fase, pois é "adiar" no design).
- Tirar de `backend/requirements.txt`: `qdrant-client`, `sentence-transformers`.

- [ ] **Step 2: Página `/live` + votação**
- Remover `backend/src/routes/live.py` e seu registro em `main.py`.
- No `frontend/src/main.tsx`, remover a rota `/live`; remover as páginas/componentes Live e Voting (`frontend/src/pages/Live*`, componentes de voto).

- [ ] **Step 3: Caminho Gemini (Claude-only)**
- Em `backend/src/agent.py`, remover os ramos `if model.startswith("gemini")` e as funções `GEMINI_*_PROMPT`/variantes; manter só o caminho Claude (SDK).
- Remover `backend/src/services/gemini_service.py`; tirar `google-generativeai` do `requirements.txt`; remover `gemini_models`/`GOOGLE_API_KEY` da config e do `.env.example`.
- No frontend, tirar os modelos Gemini do seletor de modelo.

- [ ] **Step 4: Lixo do autor**
```bash
cd /d/Sismais/Fontes/ai-orquestrator-agent
git rm -f amanha.txt todo.txt todos2.txt hello.py prompt.txt image.png 2>/dev/null || rm -f amanha.txt todo.txt todos2.txt hello.py prompt.txt image.png
```

- [ ] **Step 5: Verificar que ainda sobe**
Reinstalar deps (agora sem qdrant/gemini): `cd backend && . venv/Scripts/activate && pip install -r requirements.txt`. Subir `python -m src.main` + `npm run dev`. Board carrega, sem imports quebrados.

- [ ] **Step 6: Commit**
```bash
git add -A
git commit -m "chore(fork): corta Qdrant, pagina /live, caminho Gemini e arquivos-lixo"
```

---

## Task 5: Rebrand + LICENSE

- [ ] **Step 1: LICENSE (MIT + atribuição)** — criar `LICENSE` com o texto MIT, `Copyright (c) 2026 Sismais` **e** uma linha de atribuição ao autor original (`eduwxyz`, projeto Zenflow / orquestrator-agent), preservando o crédito conforme a licença declarada no upstream.

- [ ] **Step 2: Nome** — trocar "Zenflow"/"Kanban Agent" por **"Sismais AI Orquestrador"** em: `README.md` (título + descrição), `package.json` (`name`), `frontend/package.json` (`name`), e o título/branding visível no frontend (ex.: `frontend/src/pages/*` header, `index.html` `<title>`). Adicionar no README uma nota "fork de eduwxyz/orquestrator-agent (MIT)".

- [ ] **Step 3: Verificar + commit**
Subir o app; conferir o novo título na aba/header.
```bash
git add -A
git commit -m "chore(brand): renomeia para Sismais AI Orquestrador + LICENSE (MIT+atribuicao)"
```

---

## Task 6: Mapa do código (entrega pras Fases 2–4)

**Files:**
- Create: `docs/notes/2026-06-17-fork-code-map.md`

- [ ] **Step 1: Escrever o mapa** com os pontos que as próximas fases vão tocar (consolidando as análises):
  - **Máquina de estados/colunas (hardcoded em 3 lugares):** `frontend/src/types/index.ts` (`COLUMNS`, `ALLOWED_TRANSITIONS`, `isValidTransition`), `backend/src/repositories/card_repository.py` (`ALLOWED_TRANSITIONS`), `backend/src/schemas/card.py` (`ColumnId`). → Fase 2 (workflow como config) unifica os três + o mapa coluna→comando.
  - **Runner (browser):** `frontend/src/hooks/useWorkflowAutomation.ts` (sequência + recovery acoplada aos nomes de etapa). → Fase 3 move pro backend.
  - **Invocação do SDK / prompts:** `backend/src/agent.py` (`execute_plan/implement/test/review`, `cwd`=worktree, `setting_sources`, prompt=`/comando`). → Fase 3 religa aos nossos agentes.
  - **Worktree:** `backend/src/git_workspace.py` (`create_worktree`, cap de concorrência, cleanup). Reusar.
  - **Custo/tokens (já config-driven):** `backend/src/config/pricing.py`, `cost_calculator.py`, `ResultMessage.usage`. Reusar.
  - **Multi-projeto (global/most-recent):** `ActiveProject`, `DatabaseManager` (DB por projeto), `db_manager.reset()` no exit. → Fase 2 torna 1ª classe (seletor).
  - **PR/merge (gap!):** `handleCompletedReview` é stub; botão "Create PR" é placeholder. → Fase 3/4 constrói de fato.
  - **Fix-card:** `TestResultAnalyzer` + `parent_card_id`/`is_fix_card`. Reusar mais tarde.

- [ ] **Step 2: Commit**
```bash
git add docs/notes/2026-06-17-fork-code-map.md
git commit -m "docs(mapa): mapa do codigo do fork para as Fases 2-4"
```

---

## Self-Review (preenchido)

**Cobertura do escopo da Fase 1 (do design):** subir enxuto → Tasks 1,4; spike de skill-loading → Task 3 (com plano B); rebrand+LICENSE → Task 5; migrar agentes do DevKit → Task 2; mapa do código → Task 6. ✓ (Multi-projeto, workflow-config, runner no backend, board, ingestão = Fases 2–4, fora desta.)

**Placeholders:** sem TBD/TODO. A "borda `.git`-arquivo" tem plano B explícito (Task 3 Step 5). Comandos e caminhos são concretos; onde há incerteza de ambiente (linha exata do `_run_orchestrator`, existência de `.env.example`), o passo diz o que procurar/como confirmar — é fase de fundação, verificação por boot.

**Consistência:** porta 3001 usada de forma consistente (backend + Vite proxy + frontend `.env`); venv `Scripts/` (Windows) em todos os passos; `devkit/.claude/{skills,agents,commands}` referenciado igual entre Task 2, 3 e 6.

## Questões remanescentes (não bloqueiam a Fase 1)

- Confirmar a linha exata do agendamento do orchestrator em `main.py` (Task 1 Step 5) — ler o arquivo no início.
- Se o spike (Task 3) exigir o plano B (worktree-copy), a Fase 3 precisa embutir a cópia de `devkit/.claude` na criação da worktree (nota no mapa).
- Auth do `claude-agent-sdk`: confirmar se usa `ANTHROPIC_API_KEY` ou o login do Claude Code (validar no spike).
