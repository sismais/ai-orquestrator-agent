import pytest

from src.services import validate_ci_stage as vci
from src.services import pr_service
from src.services.stage_runner import StageResult


class FakeGm:
    async def commit_all(self, wt, msg, exclude=None):
        return True, "ok"

    async def diff_against_base(self, wt, base):
        return "diff --git a/x b/x\n+y"


class FakeLog:
    async def event(self, t):
        pass

    async def flush(self):
        pass


class Obj:
    def __init__(self, **k):
        self.__dict__.update(k)


def make_stage_fn(script):
    # `model=None` na assinatura: o implement_fix do validate_ci passa `model=fix_model`
    # (mesmo contrato do run_stage real).
    calls = []

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        calls.append(stage_key)
        text = script.get(stage_key, f"{stage_key} ok")
        return StageResult(ok=True, text=text)

    return fake, calls


@pytest.fixture(autouse=True)
def patch_pr(monkeypatch):
    async def push_ok(wt, br):
        return True, ""

    async def pr_ok(wt, base, title, body):
        return True, "http://pr/1"

    async def logs(wt):
        return "ci log"

    async def noop_sleep(_):
        return None

    monkeypatch.setattr(pr_service, "push_branch", push_ok)
    monkeypatch.setattr(pr_service, "create_or_get_pr", pr_ok)
    monkeypatch.setattr(pr_service, "failing_check_logs", logs)
    monkeypatch.setattr(vci.asyncio, "sleep", noop_sleep)


def _ctx(stage_fn, max_iterations=4, validate_command=None):
    return dict(
        worktree="/wt", branch="agent/x", base_branch="main",
        card=Obj(title="T", id="c1", description="d"),
        project=Obj(validate_command=validate_command),
        gm=FakeGm(), log=FakeLog(), stage_fn=stage_fn, max_iterations=max_iterations,
    )


async def test_ci_none_goes_ready(monkeypatch):
    async def status(wt):
        return {"state": "none", "failing": []}
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, calls = make_stage_fn({})
    res = await vci.run_validate_ci(**_ctx(fake))
    assert res["status"] == "ok" and res["pr_url"].startswith("http")


async def test_ci_pass_goes_ready(monkeypatch):
    async def status(wt):
        return {"state": "pass", "failing": []}
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, _ = make_stage_fn({})
    res = await vci.run_validate_ci(**_ctx(fake))
    assert res["status"] == "ok"


async def test_ci_fail_related_fixes_then_ready(monkeypatch):
    seq = [{"state": "fail", "failing": ["build"]}, {"state": "pass", "failing": []}]
    async def status(wt):
        return seq.pop(0)
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, calls = make_stage_fn({"ci-triage": '{"verdict":"related"}', "implement": "corrigido"})
    res = await vci.run_validate_ci(**_ctx(fake))
    assert res["status"] == "ok"
    assert "ci-triage" in calls and "implement" in calls


async def test_ci_fail_unrelated_proceeds(monkeypatch):
    async def status(wt):
        return {"state": "fail", "failing": ["flaky"]}
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, calls = make_stage_fn({"ci-triage": '{"verdict":"unrelated","porque":"flaky"}'})
    res = await vci.run_validate_ci(**_ctx(fake))
    assert res["status"] == "ok"
    assert "implement" not in calls  # nao tentou corrigir


async def test_ci_fail_related_teto_pausa(monkeypatch):
    async def status(wt):
        return {"state": "fail", "failing": ["build"]}  # sempre vermelho
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, _ = make_stage_fn({"ci-triage": '{"verdict":"related"}', "implement": "ok"})
    res = await vci.run_validate_ci(**_ctx(fake, max_iterations=1))
    assert res["status"] == "pause"


async def test_local_validate_fail_then_fix(monkeypatch):
    # validateCommand definido: 1a falha, 2a passa
    seq = [(False, "boom"), (True, "ok")]
    async def run_cmd(wt, cmd):
        return seq.pop(0)
    async def status(wt):
        return {"state": "none", "failing": []}
    monkeypatch.setattr(vci, "_run_command", run_cmd)
    monkeypatch.setattr(pr_service, "check_status", status)
    fake, calls = make_stage_fn({"implement": "corrigido"})
    res = await vci.run_validate_ci(**_ctx(fake, validate_command="npm test"))
    assert res["status"] == "ok"
    assert "implement" in calls


async def test_fix_sem_output_pausa(monkeypatch):
    # implementer encerra o turno sem texto -> pausa (nao commita nem segue cego)
    async def run_cmd(wt, cmd):
        return False, "boom"
    monkeypatch.setattr(vci, "_run_command", run_cmd)
    fake, _ = make_stage_fn({"implement": ""})
    res = await vci.run_validate_ci(**_ctx(fake, validate_command="npm test"))
    assert res["status"] == "pause"
    assert "sem output" in res["reason"]


async def test_contexto_custo_e_modelo_propagam_nos_dispatches(monkeypatch):
    # stage_context chega ao header dos prompts; account_fn contabiliza cada dispatch;
    # fix_model vai para o implementer.
    seq = [{"state": "fail", "failing": ["build"]}, {"state": "pass", "failing": []}]
    async def status(wt):
        return seq.pop(0)
    monkeypatch.setattr(pr_service, "check_status", status)

    dispatches: dict = {}
    accounted: list = []

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        dispatches[stage_key] = (prompt, model)
        text = {"ci-triage": '{"verdict":"related"}', "implement": "corrigido"}[stage_key]
        return StageResult(ok=True, text=text, cost_usd=0.5)

    async def account(res):
        accounted.append(res.cost_usd)

    ctx = _ctx(fake)
    ctx.update(stage_context={"rules_file": "REGRAS.md", "project_name": "proj"},
               account_fn=account, fix_model="opus-4.8")
    res = await vci.run_validate_ci(**ctx)
    assert res["status"] == "ok"
    assert "REGRAS.md" in dispatches["ci-triage"][0]
    assert "REGRAS.md" in dispatches["implement"][0]
    assert dispatches["implement"][1] == "opus-4.8"
    assert accounted == [0.5, 0.5]  # triage + fix, ambos contabilizados


async def test_ci_triage_recebe_modelo_explicito(monkeypatch):
    # N1: o ci-triage roda no mesmo modelo dos fixes (fix_model), nao no default do CLI.
    seq = [{"state": "fail", "failing": ["build"]}, {"state": "pass", "failing": []}]
    async def status(wt):
        return seq.pop(0)
    monkeypatch.setattr(pr_service, "check_status", status)

    dispatches: dict = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        dispatches[stage_key] = (prompt, model)
        text = {"ci-triage": '{"verdict":"related"}', "implement": "corrigido"}[stage_key]
        return StageResult(ok=True, text=text)

    ctx = _ctx(fake)
    ctx.update(fix_model="fable-5")
    res = await vci.run_validate_ci(**ctx)
    assert res["status"] == "ok"
    assert dispatches["ci-triage"][1] == "fable-5"
    assert dispatches["implement"][1] == "fable-5"
