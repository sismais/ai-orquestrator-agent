# Onda N5 — send_to_user + auditoria de tool calls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A auditoria vira "total" e o progresso vira visível: (1) as **tool calls** do agente (Read/Edit/Bash/…) são capturadas como logs tipados `tool` — hoje só o texto é registrado, então não se sabe o que o agente fez; (2) uma tool in-process **`send_to_user`** (padrão Anthropic 2) permite o agente reportar progresso ao card sem encerrar o turno, com instrução explícita de uso no system prompt. Dimensão 5 da revisão estratégica.

**Architecture:** Dois campos independentes, ambos passam pelo `on_log` (o sink já persiste ExecutionLog + transmite por WS). (1) Em `_run_single_attempt`, além de `TextBlock`, capturar `ToolUseBlock` (nome + resumo do input) e `ToolResultBlock` com erro, emitindo via `on_log(texto, "tool")` — o `on_log` ganha um 2º parâmetro `log_type="info"` (compatível: chamadas de 1 arg seguem funcionando). (2) `send_to_user` é uma SDK MCP tool criada por run em `_run_single_attempt` (closure sobre `on_log`), plugada via `mcp_servers` + `allowed_tools` nas options; emite `on_log(msg, "progress")`. Como o handler da tool pode interleaver com o drain de `receive_response`, o `_LogSink` ganha um `asyncio.Lock` protegendo `_emit`/`flush` (writes serializados na sessão do pipeline). Tools sem `on_log` (tests) não instanciam o MCP server — zero mudança de contrato do `stage_fn`.

**Frontend:** o `ExecutionLog.type` já inclui `tool`; adicionar `progress`; o LogsModal já estiliza `tool` — adicionar estilo de `progress`. PipelineControls mapeia os novos tipos (hoje mapeia system→result, error→error, resto→info; passar `tool`/`progress` adiante).

**Estado relevante (pós-N3):** `_LogSink` em `pipeline_service.py` (`__call__(text)`, `event(text)`, `_emit(log_type, content)`, flush a 800 chars); `run_stage`→`_run_single_attempt` em `stage_runner.py` (captura só TextBlock); `build_stage_options` monta as options; `AUTONOMY_SNIPPET` apendado ao system prompt; `execution_ws_manager.notify_log(card_id, log_type, content)` já aceita o tipo.

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes — ignorar). Front: `cd frontend && npx tsc --noEmit` (baseline: 3 TS6133). Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `on_log` tipado + captura de tool calls na auditoria

**Files:**
- Modify: `backend/src/services/pipeline_service.py` (`_LogSink`: log_type no `__call__` + `asyncio.Lock`)
- Modify: `backend/src/services/stage_runner.py` (`_run_single_attempt`: captura ToolUseBlock/ToolResultBlock)
- Test: `backend/tests/test_stage_runner_load.py` (novo teste de captura), `backend/tests/test_pipeline_service.py`

- [ ] **Step 1.1: Write the failing tests**

Em `backend/tests/test_stage_runner_load.py`:

```python
async def test_run_stage_captura_tool_calls(monkeypatch):
    """N5: ToolUseBlock do agente vira log tipado 'tool' via on_log."""
    from src.services import stage_runner
    from src.services.stage_runner import _AttemptOutcome

    logs: list[tuple] = []

    async def on_log(text, log_type="info"):
        logs.append((log_type, text))

    # _run_single_attempt real e complexo (SDK); este teste cobre o formatador de tool.
    from src.services.stage_runner import _format_tool_use
    assert "Edit" in _format_tool_use("Edit", {"file_path": "a.py", "old_string": "x"})
    assert "a.py" in _format_tool_use("Edit", {"file_path": "a.py"})
    assert _format_tool_use("Bash", {"command": "ls -la"}).startswith("Bash")
```

Em `backend/tests/test_pipeline_service.py`:

```python
async def test_logsink_aceita_tipo_e_persiste(maker):
    """_LogSink.__call__(text, log_type) persiste ExecutionLog com o tipo (N5)."""
    from src.services.pipeline_service import _LogSink
    from src.models.execution import Execution, ExecutionLog, ExecutionStatus
    from sqlalchemy import select
    async with maker() as s:
        ex = Execution(card_id="c1", status=ExecutionStatus.RUNNING, command="pipeline", is_active=True)
        s.add(ex)
        await s.flush()
        sink = _LogSink(s, ex.id, "c1")
        await sink("li o arquivo X", "tool")
        await sink.flush()
        rows = (await s.execute(select(ExecutionLog).where(ExecutionLog.execution_id == ex.id))).scalars().all()
    assert any(r.type == "tool" and "arquivo X" in r.content for r in rows)
```

- [ ] **Step 1.2:** Rodar — Expected: FAIL (`_format_tool_use` inexistente; `_LogSink.__call__` não aceita tipo).

- [ ] **Step 1.3: `_LogSink` tipado + lock** — em `backend/src/services/pipeline_service.py`:

1. No topo, garantir `import asyncio`.
2. `_LogSink.__init__`: adicionar `self._lock = asyncio.Lock()`.
3. `__call__` passa a aceitar o tipo e a rotear não-info direto (tool/progress não devem esperar o buffer de 800 chars de texto):

```python
    async def __call__(self, text: str, log_type: str = "info") -> None:
        if log_type != "info":
            # tool/progress: drena o buffer de texto e emite imediatamente (ordem preservada)
            await self.flush()
            await self._emit(log_type, text)
            return
        self._buf.append(text)
        self._size += len(text)
        if self._size >= _LOG_FLUSH_CHARS:
            await self.flush()
```

4. Envolver o corpo de `flush` e de `_emit` no lock (para o caller concorrente do send_to_user):

```python
    async def flush(self) -> None:
        async with self._lock:
            if not self._buf:
                return
            chunk = "".join(self._buf)
            self._buf.clear()
            self._size = 0
            await self._emit_locked("info", chunk)

    async def event(self, text: str) -> None:
        await self.flush()
        async with self._lock:
            await self._emit_locked("system", text)

    async def _emit(self, log_type: str, content: str) -> None:
        async with self._lock:
            await self._emit_locked(log_type, content)

    async def _emit_locked(self, log_type: str, content: str) -> None:
        self.s.add(ExecutionLog(
            execution_id=self.eid, type=log_type, content=content, sequence=self._seq,
        ))
        self._seq += 1
        await self.s.commit()
        try:
            await execution_ws_manager.notify_log(self.cid, log_type, content)
        except Exception:  # noqa: BLE001 — WS nao pode derrubar o pipeline
            pass
```

(o `__call__` com `log_type != "info"` chama `self.flush()` e depois `self._emit(...)` — ambos pegam o lock; `flush` chama `_emit_locked` já dentro do lock. Confira que não há re-entrância do lock: `flush` NÃO deve chamar `_emit` (que re-pega o lock) — use `_emit_locked` dentro de `flush`/`event`, e `_emit` público só para chamadas externas soltas.)

- [ ] **Step 1.4: Captura de tool calls** — em `backend/src/services/stage_runner.py`:

1. Import dos blocos: adicionar `ToolUseBlock, ToolResultBlock` ao import de `claude_agent_sdk`.
2. Formatador (após `_format_findings`):

```python
_TOOL_INPUT_HINT = {
    "Edit": ("file_path",), "Write": ("file_path",), "Read": ("file_path",),
    "Bash": ("command",), "Glob": ("pattern",), "Grep": ("pattern",),
}


def _format_tool_use(name: str, tool_input: dict) -> str:
    """Resumo de 1 linha de uma tool call para o log de auditoria (sem despejar payload)."""
    hint_keys = _TOOL_INPUT_HINT.get(name, ())
    parts = [str(tool_input.get(k)) for k in hint_keys if tool_input.get(k)]
    detail = f": {parts[0]}" if parts else ""
    return f"{name}{detail}"[:200]
```

3. No laço de `_run_single_attempt`, dentro do `if isinstance(message, AssistantMessage):`, tratar os blocos de tool (além do TextBlock existente):

```python
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
                        if on_log:
                            r = on_log(block.text)
                            if inspect.isawaitable(r):
                                await r
                    elif isinstance(block, ToolUseBlock) and on_log:
                        r = on_log(f"🔧 {_format_tool_use(block.name, block.input or {})}", "tool")
                        if inspect.isawaitable(r):
                            await r
```

E, para capturar erros de tool (tool result de erro chega em `UserMessage`/`ToolResultBlock` — o SDK entrega em mensagens de tipo `UserMessage` com content de blocos): adicionar, no laço, o tratamento defensivo (só se o tipo existir):

```python
            elif type(message).__name__ == "UserMessage":
                for block in getattr(message, "content", []) or []:
                    if isinstance(block, ToolResultBlock) and block.is_error and on_log:
                        content = block.content if isinstance(block.content, str) else str(block.content)
                        r = on_log(f"⚠️ tool falhou: {content[:200]}", "tool")
                        if inspect.isawaitable(r):
                            await r
```

(NOTA: `on_log` agora é chamado com 2 args nesses pontos; o `on_log` do pipeline é o `_LogSink` já tipado. Em `agent_chat` o `on_log` não é usado por este caminho. Confirme que os call sites de `on_log(block.text)` para texto continuam com 1 arg — default "info".)

- [ ] **Step 1.5:** `pytest tests/test_stage_runner_load.py tests/test_pipeline_service.py tests/test_stage_runner_resilience.py -v` — PASS. Suíte completa (`| tail -3`).

- [ ] **Step 1.6: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/src/services/stage_runner.py backend/tests/test_stage_runner_load.py backend/tests/test_pipeline_service.py
git commit -m "feat(auditoria): captura tool calls do agente como logs tipados; _LogSink tipado com lock (N5)"
```

---

### Task 2: tool `send_to_user` (progresso ao card) + instrução no prompt

**Files:**
- Modify: `backend/src/services/stage_runner.py` (`build_stage_options` com mcp_server opcional + snippet)
- Test: `backend/tests/test_stage_runner_load.py`

- [ ] **Step 2.1: Write the failing tests** — em `backend/tests/test_stage_runner_load.py`:

```python
def test_build_stage_options_sem_progress_nao_registra_mcp():
    from src.services.stage_runner import build_stage_options
    opts = build_stage_options("implement", "/wt", "opus-4.8")
    assert not getattr(opts, "mcp_servers", None)     # sem callback -> sem tool
    assert "PROGRESSO" in opts.system_prompt["append"] or "send_to_user" in opts.system_prompt["append"]


async def test_send_to_user_tool_emite_progress():
    from src.services.stage_runner import _make_progress_server
    emitted: list = []

    async def on_log(text, log_type="info"):
        emitted.append((log_type, text))

    server, tool_name = _make_progress_server(on_log)
    assert tool_name.endswith("send_to_user")
    # invoca o handler da tool diretamente (contrato SDK: dict -> {"content": [...]})
    from src.services.stage_runner import _progress_handler_for
    handler = _progress_handler_for(on_log)
    out = await handler({"message": "implementei o service X"})
    assert emitted == [("progress", "implementei o service X")]
    assert "content" in out
```

- [ ] **Step 2.2:** Rodar — Expected: FAIL.

- [ ] **Step 2.3: Implementar** — em `backend/src/services/stage_runner.py`:

1. Imports: `from claude_agent_sdk import create_sdk_mcp_server, tool` (além dos existentes).
2. Snippet de instrução de uso (após `AUTONOMY_SNIPPET`):

```python
# Instrucao de uso da tool send_to_user (padrao Anthropic 2). Definir a tool nao basta —
# o system prompt precisa dizer QUANDO usa-la.
PROGRESS_SNIPPET = (
    "\n\n## Progresso (send_to_user)\n"
    "Voce tem a tool `send_to_user`. Use-a para reportar progresso ao humano em marcos "
    "significativos (ex.: 'li o AGENTS.md e o modulo X', 'implementei o service, faltam os testes', "
    "'rodando a validacao') — SEM encerrar o turno. Mensagens curtas (1 frase). Nao a use para o "
    "resultado final (esse vai no formato pedido) nem para cada micro-passo."
)

_PROGRESS_SERVER_NAME = "sismais"
_PROGRESS_TOOL = "send_to_user"
PROGRESS_TOOL_FQN = f"mcp__{_PROGRESS_SERVER_NAME}__{_PROGRESS_TOOL}"


def _progress_handler_for(on_log):
    async def _handler(args: dict) -> dict:
        msg = (args or {}).get("message") or ""
        if on_log and msg:
            try:
                r = on_log(str(msg)[:500], "progress")
                if inspect.isawaitable(r):
                    await r
            except Exception:  # noqa: BLE001 — progresso e best-effort
                pass
        return {"content": [{"type": "text", "text": "ok"}]}
    return _handler


def _make_progress_server(on_log):
    """Cria o MCP server in-process com a tool send_to_user (closure sobre on_log)."""
    handler = _progress_handler_for(on_log)
    decorated = tool(_PROGRESS_TOOL, "Reporta uma mensagem curta de progresso ao humano no card, "
                     "sem encerrar o turno.", {"message": str})(handler)
    server = create_sdk_mcp_server(name=_PROGRESS_SERVER_NAME, tools=[decorated])
    return server, PROGRESS_TOOL_FQN
```

3. `build_stage_options` ganha `progress_cb=None`:

```python
def build_stage_options(stage_key: str, worktree: str, model: "str | None",
                        progress_cb=None) -> ClaudeAgentOptions:
    body, tools = load_stage_agent(stage_key)
    profile = get_profile(model) if model else None
    append = body + AUTONOMY_SNIPPET + PROGRESS_SNIPPET + (profile.prompt_append if profile else "")
    allowed = list(tools)
    options_kwargs = dict(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": append},
        permission_mode="acceptEdits",
    )
    if progress_cb is not None:
        server, fqn = _make_progress_server(progress_cb)
        options_kwargs["mcp_servers"] = {_PROGRESS_SERVER_NAME: server}
        allowed.append(fqn)
    options_kwargs["allowed_tools"] = allowed
    if model:
        options_kwargs["model"] = profile.model_id
    return ClaudeAgentOptions(**options_kwargs)
```

4. Em `_run_single_attempt`, passar o `on_log` como `progress_cb`:

```python
    options = build_stage_options(stage_key, worktree, model_alias, progress_cb=on_log)
```

- [ ] **Step 2.4:** `pytest tests/test_stage_runner_load.py tests/test_stage_runner_resilience.py tests/test_pipeline_model_wiring.py -v` — PASS (os testes que checavam `opts.system_prompt["append"]` continuam válidos; o snippet de progresso é aditivo). Ajustar o `test_build_stage_options_inclui_snippet_de_autonomia` se ele fizer assert de igualdade exata do append (ele usa `in`, então segue verde). Suíte completa.

- [ ] **Step 2.5: Commit**

```bash
git add backend/src/services/stage_runner.py backend/tests/test_stage_runner_load.py
git commit -m "feat(progresso): tool in-process send_to_user + instrucao de uso no system prompt (N5)"
```

---

### Task 3: frontend — tipos de log `progress` no LogsModal e no PipelineControls

**Files:**
- Modify: `frontend/src/types/index.ts` (`ExecutionLog.type` + `progress`)
- Modify: `frontend/src/components/LogsModal/LogsModal.tsx` + `.module.css`
- Modify: `frontend/src/components/PipelineControls/PipelineControls.tsx` (mapear tool/progress)

- [ ] **Step 3.1:** Em `frontend/src/types/index.ts`, na linha `type: 'info' | 'tool' | 'text' | 'error' | 'result';`, adicionar `'progress'`:

```typescript
  type: 'info' | 'tool' | 'text' | 'error' | 'result' | 'progress';
```

- [ ] **Step 3.2:** Em `frontend/src/components/LogsModal/LogsModal.tsx`, no `getLogTypeClass`, adicionar o case (após `'tool'`):

```tsx
      case 'progress': return styles.logProgress;
```

Em `LogsModal.module.css`, adicionar (perto de `.logTool`):

```css
.logProgress .logType { color: #22c55e; }
.logProgress { border-left: 3px solid #22c55e; }
```

- [ ] **Step 3.3:** Em `frontend/src/components/PipelineControls/PipelineControls.tsx`, no `onLog` (que hoje mapeia `error`→error, `system`→result, resto→info), preservar tool/progress:

```tsx
  const onLog = useCallback((msg: { logType: string; content: string; timestamp: string }) => {
    const type: ExecutionLog['type'] =
      msg.logType === 'error' ? 'error'
      : msg.logType === 'system' ? 'result'
      : msg.logType === 'tool' ? 'tool'
      : msg.logType === 'progress' ? 'progress'
      : 'info';
    setLogs(prev => [...prev, { timestamp: msg.timestamp, type, content: msg.content }]);
  }, []);
```

- [ ] **Step 3.4:** `cd frontend && npx tsc --noEmit` — baseline de 3 erros.

- [ ] **Step 3.5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/components/LogsModal/LogsModal.tsx frontend/src/components/LogsModal/LogsModal.module.css frontend/src/components/PipelineControls/PipelineControls.tsx
git commit -m "feat(painel): logs de tool e progresso renderizados distintamente no LogsModal (N5)"
```

---

### Task 4: suite completa + docs

- [ ] **Step 4.1:** Suíte completa backend + tsc front (baselines).

- [ ] **Step 4.2:** Em `docs/ARQUITETURA_E_ESTADO.md`, após a N3:

```markdown
### Onda N5 — send_to_user + auditoria de tool calls — feito 2026-07-10
- **Auditoria total:** as tool calls do agente (Read/Edit/Bash/…) viram logs tipados `tool`
  (`stage_runner._format_tool_use`) — antes só o texto era registrado; erros de tool também.
  `_LogSink.__call__` aceita `log_type` e serializa writes com `asyncio.Lock`.
- **Progresso:** tool in-process **`send_to_user`** (SDK MCP, padrão Anthropic 2) plugada por run
  via `build_stage_options(progress_cb=)`; emite logs `progress` ao card sem encerrar o turno;
  `PROGRESS_SNIPPET` instrui o uso no system prompt (definir a tool não basta).
- Front: LogsModal e PipelineControls renderizam `tool`/`progress` distintamente.
- Plano: `plans/2026-07-10-onda-n5-send-to-user-auditoria.md`.
```

- [ ] **Step 4.3: Commit**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda N5 (send_to_user + auditoria de tool calls)"
```

## Self-review (feito na escrita)

- Contrato `stage_fn` inalterado: `progress_cb` é interno de `_run_single_attempt`→`build_stage_options`; fakes do pipeline/validate_ci não passam por aí.
- `_LogSink` com lock: o send_to_user (handler concorrente) e o drain de texto não corrompem a sessão nem o `_seq`. Tool/progress fazem flush do buffer de texto antes de emitir → ordem cronológica preservada.
- Best-effort em tudo: falha no handler de progresso ou na captura de tool nunca derruba o turno (guardados).
- Volume de log: tool calls resumidas a 1 linha (≤200 chars), progresso ≤500 — sem despejar payloads. Aceitável para SQLite.
- `ToolResultBlock` em `UserMessage`: tratado defensivamente por `type(...).__name__` para não quebrar se o SDK entregar o erro noutro formato (fallback: só o TextBlock é obrigatório).
