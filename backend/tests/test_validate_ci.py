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
    calls = []

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None):
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
