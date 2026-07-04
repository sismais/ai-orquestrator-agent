import json
import pytest

from src.services import pr_service


def _rollup(items):
    return json.dumps({"statusCheckRollup": items})


async def _patch_run(monkeypatch, out, rc=0):
    async def fake_run(args, cwd):
        return rc, out, ""
    monkeypatch.setattr(pr_service, "_run", fake_run)


async def test_check_status_none_when_empty(monkeypatch):
    await _patch_run(monkeypatch, _rollup([]))
    assert (await pr_service.check_status("/wt"))["state"] == "none"


async def test_check_status_pass(monkeypatch):
    await _patch_run(monkeypatch, _rollup([
        {"__typename": "CheckRun", "name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"},
    ]))
    assert (await pr_service.check_status("/wt"))["state"] == "pass"


async def test_check_status_pending(monkeypatch):
    await _patch_run(monkeypatch, _rollup([
        {"__typename": "CheckRun", "name": "build", "status": "IN_PROGRESS", "conclusion": None},
    ]))
    assert (await pr_service.check_status("/wt"))["state"] == "pending"


async def test_check_status_fail_lists_names(monkeypatch):
    await _patch_run(monkeypatch, _rollup([
        {"__typename": "CheckRun", "name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]))
    s = await pr_service.check_status("/wt")
    assert s["state"] == "fail" and "test" in s["failing"]


async def test_check_status_no_pr(monkeypatch):
    await _patch_run(monkeypatch, "", rc=1)  # gh falha (sem PR)
    assert (await pr_service.check_status("/wt"))["state"] == "none"
