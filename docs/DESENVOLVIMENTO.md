# Sismais AI Orquestrador — Desenvolvimento (como rodar/testar)

> Ambiente: **Windows + Git Bash**. venv do backend em `backend/venv/Scripts/` (não `bin/`).
> O `Makefile` assume Linux — no Windows rode os comandos manualmente.

## Rodar

### Backend (porta 3001)
```bash
cd backend
python -m venv venv                      # 1ª vez
. venv/Scripts/activate                  # Windows/Git Bash
pip install -r requirements.txt          # inclui pydantic[email]; NÃO precisa sentence-transformers
./venv/Scripts/python.exe -m src.main     # sobe em :3001
```
- `.env` (gitignored) — **sem `ANTHROPIC_API_KEY`** (usa a assinatura Max do CLI). Chaves:
  `DATABASE_URL=sqlite+aiosqlite:///./orchestrator.db`, `PORT=3001`, `ORCHESTRATOR_ENABLED=false`,
  `JWT_SECRET_KEY=...`. Copie de `.env.example` se faltar.
- No boot: cria tabelas → `light_migrations` → `remap_legacy_columns` → semeia o workflow `dev`.
  Confirme no log: `Dev workflow seeded`.

### Frontend (porta 5173)
```bash
cd frontend
npm install
printf 'VITE_API_URL=http://localhost:3001\nVITE_WS_URL=ws://localhost:3001\n' > .env
npm run dev
```

## Testes

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v
```
- **Baseline:** `test_project_manager.py` e `test_test_result_analyzer.py` têm ~10 falhas
  **pré-existentes do fork** — ignore; foque nas suas.
- Testes de rota usam `httpx.AsyncClient` + `ASGITransport` com `monkeypatch` do `async_session_maker`
  p/ engine em memória. **Inclua `import src.models` no topo** do teste p/ registrar todos os models no
  `Base.metadata` (senão `create_all` roda incompleto ao executar o arquivo sozinho).
- Frontend: sem ESLint config; gate é `npx tsc --noEmit` (há ~7 erros pré-existentes `Cannot find
  namespace 'NodeJS'` — confira via `git stash` que você não introduziu novos).

## Gotchas (aprendidos na prática)

- **Processos zumbis na 3001:** subir com `&` no Git Bash + `kill` **não mata** o python de verdade;
  a porta fica presa. Mate por PowerShell antes de rebootar:
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -like '*src.main*' } | % { Stop-Process -Id $_.ProcessId -Force }
  ```
- **`taskkill /PID`** no Git Bash é mangled (MSYS converte `/PID` em path) — use PowerShell.
- **WAL + kill abrupto:** ao checar o `.db` após matar o server, dados podem estar no `-wal`; prefira
  reabrir via boot limpo. O `.env` sobrepõe o default de `DATABASE_URL` — confira qual arquivo está em uso.
- **Python 3.13:** `sentence-transformers` (torch) costuma quebrar build — está fora do `requirements`.

## Repo-alvo de teste

- **`maiconsaraiva/spike-loop-test`** (clone local `D:\Sismais\Fontes\spike-loop-test`) — repo criado
  **exclusivamente pra testar o runner**. Registre-o como projeto e crie cards de tarefa pequena.
- O runner cria worktrees em `<repo>/.worktrees/card-<id>` na branch `agent/<id>-<ts>` — pode limpar com
  `git worktree remove <path> --force` + `git branch -D <branch>` no repo-alvo.

## Smoke do runner (execução real — gasta Max)

```bash
# registrar projeto
curl -s -X POST localhost:3001/api/registry/projects -H 'Content-Type: application/json' \
  -d '{"name":"spike-loop-test","path":"D:/Sismais/Fontes/spike-loop-test","workflowId":"dev","baseBranch":"main"}'
# criar card (pegue o id) e executar
curl -s -X POST "localhost:3001/api/projects/<PID>/cards/<CID>/execute"
# verificar: ls D:/Sismais/Fontes/spike-loop-test/.worktrees/card-<id8>/
```

## Fluxo git deste fork

- Trabalho **direto na `main`** do fork privado `sismais/ai-orquestrator-agent` (setup do dono).
- ⚠️ Um hook do **gms-mobile** (`guard-direct-push.mjs`) bloqueia `git push origin main` — é falso
  positivo aqui (guarda a prod do gms). Push do fork com `git push` **simples** (bare) a partir do dir do fork.
