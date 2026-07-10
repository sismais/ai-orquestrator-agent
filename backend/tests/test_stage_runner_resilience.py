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
