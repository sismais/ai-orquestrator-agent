import asyncio
import subprocess
from pathlib import Path

from src.git_workspace import GitWorkspaceManager


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


async def test_commit_all_and_diff_against_base(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "readme.md").write_text("hello")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")

    gm = GitWorkspaceManager(str(repo))
    wt = await gm.create_worktree("card1234", "main")
    assert wt.success, wt.error

    # escreve arquivo novo na worktree e commita
    Path(wt.worktree_path, "novo.py").write_text("def soma(a,b):\n    return a+b\n")
    ok, out = await gm.commit_all(wt.worktree_path, "wip: soma")
    assert ok, out

    diff = await gm.diff_against_base(wt.worktree_path, "main")
    assert "novo.py" in diff


async def test_commit_all_nothing_to_commit_is_ok(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "readme.md").write_text("hello")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")

    gm = GitWorkspaceManager(str(repo))
    wt = await gm.create_worktree("card9999", "main")
    ok, out = await gm.commit_all(wt.worktree_path, "sem mudancas")
    assert ok  # nothing to commit tambem e sucesso
