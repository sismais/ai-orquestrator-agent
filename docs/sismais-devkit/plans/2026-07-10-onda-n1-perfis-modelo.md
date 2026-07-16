# Onda N1 — Perfis por modelo + tratamento de recusa/erro com fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O fim de turno do SDK passa a ser inspecionado e classificado (ok / recusa / erro transiente / erro); recusa dispara retry automático com o modelo de fallback do perfil; erro transiente dispara 1 retry no mesmo modelo; `config/model_ids.py` vira registry de perfis (ponto único, padrões Anthropic 4 e 5); fable-5 é habilitado nos pickers com a rede de segurança funcionando.

**Architecture:** `run_stage` (stage_runner) vira um laço de política sobre `_run_single_attempt` (uma sessão SDK por tentativa). A classificação usa campos REAIS do claude-agent-sdk 0.2.110 instalado (verificado em `venv/Lib/site-packages/claude_agent_sdk/types.py`): `ResultMessage.stop_reason: str|None`, `is_error: bool`, `subtype: str`, `api_error_status: int|None` (HTTP 429/500/529 quando `is_error`), `errors: list[str]|None`; `AssistantMessage.stop_reason` também existe. Exceções do SDK: `ClaudeSDKError`, `CLIConnectionError`, `ProcessError`, `CLIJSONDecodeError`, `MessageParseError` (`_errors.py`). O contrato `stage_fn(stage_key, worktree, prompt, card_id=None, on_log=None, model=None)` NÃO muda — pipeline e validate_ci herdam a resiliência de graça.

**Tech Stack:** FastAPI + claude-agent-sdk 0.2.110 (backend), React+TS (frontend).

**Estado pós-onda A relevante:** `build_stage_options` é o ponto único de options (`stage_runner.py:50-62`); `StageResult` tem `usage` (Task 8); o pipeline pausa em `ok=False` e conta custo via `account(res, model_alias)`; `validate_ci_stage.run_validate_ci` recebe `stage_context`/`account_fn`/`fix_model` (fixes do review final).

**Branch:** `feat/melhorias-by-fable-5`. Testes: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -v` (3 falhas pré-existentes em `test_test_result_analyzer.py` — ignorar). Front: `cd frontend && npx tsc --noEmit` (baseline: 3 erros TS6133). Commits: mensagem indicada + linha em branco + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Registry de perfis em `config/model_ids.py`

**Files:**
- Modify: `backend/src/config/model_ids.py`
- Test: `backend/tests/test_model_ids.py`

- [ ] **Step 1.1: Write the failing tests** — adicionar a `backend/tests/test_model_ids.py`:

```python
def test_get_profile_conhecido():
    from src.config.model_ids import get_profile
    p = get_profile("fable-5")
    assert p.model_id == "claude-fable-5"
    assert p.fallback_alias == "opus-4.8"


def test_get_profile_desconhecido_usa_default():
    from src.config.model_ids import get_profile, _FALLBACK
    p = get_profile("inexistente-9")
    assert p.model_id == _FALLBACK
    p2 = get_profile(None)
    assert p2.model_id == _FALLBACK


def test_opus_nao_tem_fallback():
    from src.config.model_ids import get_profile
    assert get_profile("opus-4.8").fallback_alias is None


def test_resolve_model_id_compat():
    from src.config.model_ids import resolve_model_id
    assert resolve_model_id("opus-4.8") == "claude-opus-4-8[1m]"
    assert resolve_model_id("opus-4.5") == "claude-opus-4-8[1m]"   # legado
    assert resolve_model_id(None) == "claude-sonnet-5[1m]"
    assert resolve_model_id("qualquer") == "claude-sonnet-5[1m]"
```

- [ ] **Step 1.2:** Rodar `pytest tests/test_model_ids.py -v` — Expected: FAIL (ImportError `get_profile`).

- [ ] **Step 1.3: Implementar** — substituir o conteúdo de `backend/src/config/model_ids.py` por:

```python
"""Perfis por modelo (padroes Anthropic 4 e 5): alias de UI -> perfil.

Fonte de verdade compartilhada entre o chat (agent_chat) e o pipeline
(stage_runner/pipeline_service). Cada perfil define o id real no SDK, o alias
de fallback para RECUSA (retry automatico com outro modelo — sem isso um card
com recusa trava sem explicacao) e um snippet opcional de system prompt.
O sufixo [1m] seleciona a variante de 1M de contexto (opus 4.8 e sonnet 5 tem).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    fallback_alias: Optional[str] = None  # para onde ir em recusa (None = pausa direto)
    prompt_append: str = ""               # snippet de system prompt especifico do modelo


MODEL_PROFILES: dict[str, ModelProfile] = {
    "opus-4.8": ModelProfile("claude-opus-4-8[1m]"),
    "sonnet-5": ModelProfile("claude-sonnet-5[1m]", fallback_alias="opus-4.8"),
    "haiku-4.5": ModelProfile("claude-haiku-4-5", fallback_alias="opus-4.8"),
    "fable-5": ModelProfile("claude-fable-5", fallback_alias="opus-4.8"),
    # legados remapeados (cards antigos)
    "opus-4.5": ModelProfile("claude-opus-4-8[1m]"),
    "sonnet-4.5": ModelProfile("claude-sonnet-5[1m]", fallback_alias="opus-4.8"),
}

_FALLBACK = "claude-sonnet-5[1m]"
_DEFAULT_PROFILE = ModelProfile(_FALLBACK, fallback_alias="opus-4.8")

# Compat: mapa simples alias->id (consumidores antigos e testes)
ALIAS_TO_MODEL_ID = {alias: p.model_id for alias, p in MODEL_PROFILES.items()}


def get_profile(alias: Optional[str]) -> ModelProfile:
    """Perfil do alias de UI. Desconhecido/None -> perfil default (sonnet-5 1M)."""
    if not alias:
        return _DEFAULT_PROFILE
    return MODEL_PROFILES.get(alias, _DEFAULT_PROFILE)


def resolve_model_id(alias: Optional[str]) -> str:
    """Resolve um alias de UI para o id real do SDK. Desconhecido/None -> fallback."""
    return get_profile(alias).model_id
```

- [ ] **Step 1.4:** `pytest tests/test_model_ids.py tests/test_model_alias_migration.py -v` — Expected: PASS (compat preservada).

- [ ] **Step 1.5: Commit**

```bash
git add backend/src/config/model_ids.py backend/tests/test_model_ids.py
git commit -m "feat(modelos): registry de perfis por modelo em model_ids (N1)"
```

---

### Task 2: Classificação do fim de turno + retry/fallback no `run_stage`

**Files:**
- Modify: `backend/src/services/stage_runner.py`
- Test: `backend/tests/test_stage_runner_resilience.py` (novo), `backend/tests/test_stage_runner_load.py`

- [ ] **Step 2.1: Write the failing tests** — criar `backend/tests/test_stage_runner_resilience.py`:

```python
"""Testes da politica de retry/fallback do run_stage (N1).

_run_single_attempt e monkeypatchado — os testes exercitam SO a politica
(classificacao -> retry transiente -> fallback de recusa -> pausa), nao o SDK.
"""
import pytest

from src.services import stage_runner
from src.services.stage_runner import _AttemptOutcome, _classify_result


class _FakeResult:
    """ResultMessage minimo para _classify_result (campos do SDK 0.2.110)."""
    def __init__(self, stop_reason=None, is_error=False, subtype="success",
                 api_error_status=None):
        self.stop_reason = stop_reason
        self.is_error = is_error
        self.subtype = subtype
        self.api_error_status = api_error_status


def test_classify_ok():
    assert _classify_result(_FakeResult(), None) == "ok"


def test_classify_refusal_no_result():
    assert _classify_result(_FakeResult(stop_reason="refusal"), None) == "refusal"


def test_classify_refusal_no_assistant():
    assert _classify_result(_FakeResult(), "refusal") == "refusal"


def test_classify_transiente():
    assert _classify_result(_FakeResult(is_error=True, api_error_status=529), None) == "transient"
    assert _classify_result(_FakeResult(is_error=True, api_error_status=429), None) == "transient"


def test_classify_erro():
    assert _classify_result(_FakeResult(is_error=True, subtype="error_max_turns"), None) == "error"
    assert _classify_result(None, None) == "error"  # turno sem ResultMessage


def _mk_attempt_script(script):
    """script: lista de _AttemptOutcome devolvidos em ordem; registra os aliases pedidos."""
    calls = []

    async def fake_attempt(stage_key, worktree, prompt, card_id, on_log, model_alias):
        calls.append(model_alias)
        return script[min(len(calls) - 1, len(script) - 1)]

    return fake_attempt, calls


def _outcome(classification, text="ok", cost=0.01, interrupted=False, error=None):
    return _AttemptOutcome(
        classification=classification, text=text, cost_usd=cost,
        usage={"input_tokens": 10, "output_tokens": 5},
        interrupted=interrupted, error=error,
    )


async def test_recusa_dispara_fallback(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("refusal", text=""), _outcome("ok", text="feito")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="fable-5")
    assert res.ok is True
    assert res.text == "feito"
    assert calls == ["fable-5", "opus-4.8"]          # perfil do fable-5 -> opus-4.8
    assert res.used_model == "opus-4.8"
    assert res.cost_usd == pytest.approx(0.02)       # soma das tentativas
    assert res.usage["input_tokens"] == 20


async def test_recusa_sem_fallback_vira_erro(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("refusal", text="")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="opus-4.8")
    assert res.ok is False
    assert "recusa" in (res.error or "").lower()
    assert calls == ["opus-4.8"]                     # opus nao tem fallback: nao re-tenta


async def test_recusa_dupla_vira_erro(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("refusal"), _outcome("refusal")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="fable-5")
    assert res.ok is False
    assert "recusa" in (res.error or "").lower()
    assert calls == ["fable-5", "opus-4.8"]          # 1 fallback so, nunca cadeia


async def test_transiente_retenta_mesmo_modelo(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("transient", error="529"), _outcome("ok", text="ok2")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="sonnet-5")
    assert res.ok is True
    assert calls == ["sonnet-5", "sonnet-5"]


async def test_interrupted_nunca_retenta(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("ok", interrupted=True, text="")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="fable-5")
    assert res.interrupted is True
    assert len(calls) == 1


async def test_erro_definitivo_nao_retenta(monkeypatch):
    fake, calls = _mk_attempt_script([_outcome("error", error="error_max_turns")])
    monkeypatch.setattr(stage_runner, "_run_single_attempt", fake)
    res = await stage_runner.run_stage("implement", "/wt", "p", model="sonnet-5")
    assert res.ok is False
    assert len(calls) == 1
```

E em `backend/tests/test_stage_runner_load.py`, adicionar:

```python
def test_build_stage_options_apende_prompt_do_perfil(monkeypatch):
    from src.config.model_ids import ModelProfile
    from src.config import model_ids
    from src.services.stage_runner import build_stage_options
    monkeypatch.setitem(model_ids.MODEL_PROFILES, "teste-x",
                        ModelProfile("claude-teste", prompt_append="\nSNIPPET-DO-PERFIL"))
    opts = build_stage_options("plan", "/wt", "teste-x")
    assert "SNIPPET-DO-PERFIL" in opts.system_prompt["append"]
```

- [ ] **Step 2.2:** Rodar os dois arquivos — Expected: FAIL (ImportError `_AttemptOutcome`/`_classify_result`).

- [ ] **Step 2.3: Refatorar `run_stage`** em `backend/src/services/stage_runner.py`:

1. `build_stage_options` passa a usar o perfil (troca do import também):

```python
from ..config.model_ids import get_profile, resolve_model_id
```

```python
def build_stage_options(stage_key: str, worktree: str, model: "str | None") -> ClaudeAgentOptions:
    """Ponto unico de montagem das options do estagio (perfis por modelo — N1)."""
    body, tools = load_stage_agent(stage_key)
    profile = get_profile(model) if model else None
    append = body + AUTONOMY_SNIPPET + (profile.prompt_append if profile else "")
    options_kwargs = dict(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": append},
        allowed_tools=tools,
        permission_mode="acceptEdits",
    )
    if model:
        options_kwargs["model"] = profile.model_id
    return ClaudeAgentOptions(**options_kwargs)
```

2. Classificação (após `StageResult`):

```python
# Status HTTP que valem 1 retry no mesmo modelo (rate limit / erro de servidor).
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504, 529}


def _classify_result(result_msg, last_assistant_stop_reason: "str | None") -> str:
    """Classifica o fim do turno: 'ok' | 'refusal' | 'transient' | 'error'.

    Campos do claude-agent-sdk 0.2.110: ResultMessage.stop_reason/is_error/subtype/
    api_error_status; AssistantMessage.stop_reason (a recusa pode aparecer em qualquer um).
    Turno sem ResultMessage = stream truncado -> 'error'.
    """
    if getattr(result_msg, "stop_reason", None) == "refusal" or last_assistant_stop_reason == "refusal":
        return "refusal"
    if result_msg is None:
        return "error"
    if getattr(result_msg, "is_error", False):
        status = getattr(result_msg, "api_error_status", None)
        if status in _TRANSIENT_HTTP:
            return "transient"
        return "error"
    return "ok"
```

3. Dataclass da tentativa + extração da sessão única (o corpo atual do try/except do `run_stage` vira `_run_single_attempt`):

```python
@dataclass
class _AttemptOutcome:
    classification: str            # ok | refusal | transient | error
    text: str = ""
    cost_usd: Optional[float] = None
    usage: Optional[dict] = None
    interrupted: bool = False
    error: Optional[str] = None


async def _run_single_attempt(stage_key: str, worktree: str, prompt: str,
                              card_id: "str | None", on_log, model_alias: "str | None") -> _AttemptOutcome:
    """UMA sessao SDK: conecta, roda o turno, classifica o fim. Sem politica de retry aqui."""
    options = build_stage_options(stage_key, worktree, model_alias)
    texts: list[str] = []
    cost = None
    usage = None
    result_msg = None
    last_stop = None
    client = ClaudeSDKClient(options)
    try:
        await client.connect()
        if card_id:
            sessions.register(card_id, client)
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                last_stop = getattr(message, "stop_reason", None) or last_stop
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
                        if on_log:
                            r = on_log(block.text)
                            if inspect.isawaitable(r):
                                await r
            elif isinstance(message, ResultMessage):
                result_msg = message
                cost = getattr(message, "total_cost_usd", None)
                usage = getattr(message, "usage", None) or None
    except Exception as e:  # noqa: BLE001
        interrupted = bool(card_id and sessions.was_interrupted(card_id))
        return _AttemptOutcome(
            classification="ok" if interrupted else "error",
            text="\n".join(texts), cost_usd=cost, usage=usage,
            interrupted=interrupted, error=None if interrupted else str(e),
        )
    finally:
        if card_id:
            sessions.unregister(card_id)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    interrupted = bool(card_id and sessions.was_interrupted(card_id))
    if card_id:
        sessions.clear_interrupt(card_id)
    classification = _classify_result(result_msg, last_stop)
    error = None
    if classification != "ok" and result_msg is not None:
        detail = getattr(result_msg, "errors", None) or getattr(result_msg, "result", None)
        error = f"{getattr(result_msg, 'subtype', '?')} | {detail}" if detail else getattr(result_msg, "subtype", "erro")
    return _AttemptOutcome(
        classification=classification, text="\n".join(texts), cost_usd=cost,
        usage=usage, interrupted=interrupted, error=error,
    )
```

4. `StageResult` ganha o campo `used_model: Optional[str] = None` (após `usage`).

5. `run_stage` vira o laço de política (mesma assinatura):

```python
async def run_stage(stage_key: str, worktree: str, prompt: str, card_id: Optional[str] = None,
                    on_log=None, model: Optional[str] = None) -> StageResult:
    """Roda um estagio com resiliencia (N1): recusa -> 1 retry no modelo de fallback do
    perfil; erro transiente (HTTP 429/5xx) -> 1 retry no mesmo modelo; interrupcao nunca
    re-tenta. Custo/usage somados entre tentativas; `used_model` = alias que produziu o
    resultado final. Assinatura estavel (contrato stage_fn do pipeline/validate_ci).
    """
    total_cost = 0.0
    total_usage: dict = {}

    def _merge(outcome: _AttemptOutcome) -> None:
        nonlocal total_cost
        if outcome.cost_usd:
            total_cost += float(outcome.cost_usd)
        if isinstance(outcome.usage, dict):
            for k, v in outcome.usage.items():
                if isinstance(v, (int, float)):
                    total_usage[k] = total_usage.get(k, 0) + v

    async def _note(msg: str) -> None:
        if on_log:
            r = on_log(msg)
            if inspect.isawaitable(r):
                await r

    alias = model
    transient_retried = False
    fallback_used = False
    for _ in range(3):  # teto duro: 1 tentativa + 1 retry transiente + 1 fallback
        outcome = await _run_single_attempt(stage_key, worktree, prompt, card_id, on_log, alias)
        _merge(outcome)
        if outcome.interrupted:
            return StageResult(ok=True, text=outcome.text, cost_usd=total_cost or None,
                               interrupted=True, usage=total_usage or None, used_model=alias)
        if outcome.classification == "ok":
            return StageResult(ok=True, text=outcome.text, cost_usd=total_cost or None,
                               usage=total_usage or None, used_model=alias)
        if outcome.classification == "transient" and not transient_retried:
            transient_retried = True
            await _note(f"\n[orquestrador] erro transiente da API ({outcome.error}) — re-tentando...\n")
            continue
        if outcome.classification == "refusal" and not fallback_used:
            fallback = get_profile(alias).fallback_alias if alias else None
            if fallback:
                fallback_used = True
                await _note(f"\n[orquestrador] recusa do modelo `{alias}` — re-tentando com `{fallback}` (perfil de fallback)\n")
                alias = fallback
                continue
            return StageResult(ok=False, text=outcome.text, cost_usd=total_cost or None,
                               error=f"recusa do modelo `{alias}` (sem fallback no perfil)",
                               usage=total_usage or None, used_model=alias)
        # refusal com fallback ja usado, transient repetido, ou error definitivo
        err = outcome.error or outcome.classification
        if outcome.classification == "refusal":
            err = f"recusa persistente (modelos: {model} -> {alias})"
        return StageResult(ok=False, text=outcome.text, cost_usd=total_cost or None,
                           error=err, usage=total_usage or None, used_model=alias)
    return StageResult(ok=False, error="teto de tentativas do estagio excedido",
                       cost_usd=total_cost or None, usage=total_usage or None, used_model=alias)
```

- [ ] **Step 2.4:** `pytest tests/test_stage_runner_resilience.py tests/test_stage_runner_load.py tests/test_pipeline_service.py tests/test_validate_ci.py -v` — Expected: PASS em todos (fakes do pipeline não passam pelo run_stage real).

- [ ] **Step 2.5: Commit**

```bash
git add backend/src/services/stage_runner.py backend/tests/test_stage_runner_resilience.py backend/tests/test_stage_runner_load.py
git commit -m "feat(stage): classificacao do fim de turno + retry transiente e fallback de recusa por perfil (N1)"
```

---

### Task 3: telemetria usa o modelo REAL + ci-triage com modelo explícito

**Files:**
- Modify: `backend/src/services/pipeline_service.py` (`account`)
- Modify: `backend/src/services/validate_ci_stage.py` (ci-triage com `model=`)
- Test: `backend/tests/test_pipeline_service.py`, `backend/tests/test_validate_ci.py`

- [ ] **Step 3.1: Write the failing tests**

Em `backend/tests/test_pipeline_service.py`:

```python
async def test_account_prefere_modelo_real_do_fallback(maker):
    """N1: se o run_stage caiu no fallback, model_used registra o modelo REAL."""
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text, cost_usd=0.01, used_model="opus-4.8"
                           if stage_key != "plan" else "sonnet-5")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    ex = await _last_execution(maker, card_id)
    assert "sonnet-5" in (ex.model_used or "")
    assert "opus-4.8" in (ex.model_used or "")
```

Em `backend/tests/test_validate_ci.py` (siga o padrão de fakes do arquivo): um teste que o dispatch do ci-triage recebe `model=` igual ao `fix_model` passado (capture o kwarg no fake, como o teste de contexto/custo existente faz).

- [ ] **Step 3.2:** Rodar — Expected: FAIL.

- [ ] **Step 3.3: Implementar**

1. Em `pipeline_service.py`, dentro de `account`, trocar o bloco final:

```python
            if model_alias:
                models_used.add(model_alias)
```

por:

```python
            used = getattr(res, "used_model", None) or model_alias
            if used:
                models_used.add(used)
```

2. Em `validate_ci_stage.py`, no dispatch do ci-triage (~linha 109), adicionar `model=fix_model` à chamada `stage_fn("ci-triage", ...)` (o `fix_model` já chega como parâmetro desde o review final da onda A; o triage passa a rodar no mesmo modelo dos fixes em vez do default do CLI).

- [ ] **Step 3.4:** `pytest tests/test_pipeline_service.py tests/test_validate_ci.py -v` — Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add backend/src/services/pipeline_service.py backend/src/services/validate_ci_stage.py backend/tests/test_pipeline_service.py backend/tests/test_validate_ci.py
git commit -m "feat(telemetria): model_used registra o modelo real pos-fallback; ci-triage com modelo explicito (N1)"
```

---

### Task 4: habilitar fable-5 nos pickers (a rede de segurança agora existe)

**Files:**
- Modify: `frontend/src/components/Chat/ModelSelector.tsx`
- Modify: `frontend/src/components/AddCardModal/AddCardModal.tsx`

- [ ] **Step 4.1:** Em `ModelSelector.tsx`, na entrada `fable-5` de `AVAILABLE_MODELS`: remover `disabled: true` e trocar `badge: 'Beta'` por `badge: 'Novo'` (mantendo os demais campos). Em `AddCardModal.tsx`, na entrada `fable-5` de `MODEL_CARDS`: remover `disabled: true`. LEIA os dois arquivos antes — se o render usa `disabled` para estilo/tooltip, confirme que a remoção não deixa markup órfão.

- [ ] **Step 4.2:** `cd frontend && npx tsc --noEmit` — Expected: baseline de 3 erros TS6133.

- [ ] **Step 4.3: Commit**

```bash
git add frontend/src/components/Chat/ModelSelector.tsx frontend/src/components/AddCardModal/AddCardModal.tsx
git commit -m "feat(modelos): habilita fable-5 nos pickers — fallback de recusa ativo (N1)"
```

---

### Task 5: suite completa + docs

- [ ] **Step 5.1:** `cd backend && ./venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -3` — Expected: tudo verde exceto as 3 pré-existentes. `cd frontend && npx tsc --noEmit` — baseline.

- [ ] **Step 5.2:** Em `docs/ARQUITETURA_E_ESTADO.md`, adicionar após a seção da onda "Agora":

```markdown
### Onda N1 — perfis por modelo + recusa com fallback — feito 2026-07-10
- `config/model_ids.py` virou **registry de perfis** (`ModelProfile`: model_id, fallback_alias,
  prompt_append); `resolve_model_id`/`ALIAS_TO_MODEL_ID` preservados como compat.
- `stage_runner.run_stage` virou laço de política sobre `_run_single_attempt`: fim de turno
  **classificado** (`_classify_result` sobre `ResultMessage.stop_reason/is_error/api_error_status`
  do SDK 0.2.110) — **recusa → 1 retry no modelo de fallback do perfil** (ex.: fable-5 → opus-4.8),
  erro transiente (HTTP 429/5xx) → 1 retry no mesmo modelo, interrupção nunca re-tenta; custo/usage
  somados entre tentativas; `StageResult.used_model` = modelo real (telemetria registra pós-fallback).
- ci-triage roda com modelo explícito (`fix_model`). **fable-5 habilitado nos pickers.**
- Plano: `plans/2026-07-10-onda-n1-perfis-modelo.md`.
```

- [ ] **Step 5.3: Commit**

```bash
git add docs/ARQUITETURA_E_ESTADO.md
git commit -m "docs: registra a onda N1 (perfis por modelo + fallback de recusa)"
```

## Self-review (feito na escrita)

- Contrato `stage_fn` estável — pipeline/validate_ci/testes existentes não mudam; fakes que devolvem `StageResult` direto não passam pela política (correto: a política vive no run_stage real).
- `_run_single_attempt` preserva TODA a semântica atual de interrupt/registry/disconnect (o corpo é o try/except atual movido); a exceção genérica vira `classification="error"` → o laço NÃO re-tenta erro definitivo → `ok=False` → pipeline pausa, como hoje.
- Recusa dupla: teto de 1 fallback (sem cadeia); recusa sem fallback (opus) pausa direto com mensagem clara.
- `used_model` default None mantém `account` funcionando com fakes antigos (getattr com fallback para o alias pedido).
