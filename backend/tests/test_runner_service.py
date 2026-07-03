from src.services.runner_service import build_prompt, DEVKIT_CLAUDE


def test_build_prompt_includes_task_and_worktree():
    p = build_prompt("Somar dois numeros", "cria util soma", "/tmp/wt")
    assert "/tmp/wt" in p
    assert "Somar dois numeros" in p
    assert "cria util soma" in p


def test_devkit_claude_path_points_to_devkit():
    # aponta para <repo>/devkit/.claude
    assert DEVKIT_CLAUDE.name == ".claude"
    assert DEVKIT_CLAUDE.parent.name == "devkit"
