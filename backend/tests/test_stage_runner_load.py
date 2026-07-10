import pytest

from src.services.stage_runner import load_stage_agent, has_stage, build_stage_prompt


def test_load_review_agent_strips_frontmatter_and_maps_tools():
    body, tools = load_stage_agent("review")
    assert not body.lstrip().startswith("---")  # frontmatter removido
    assert "Reviewer" in body or "review" in body.lower()
    assert tools == ["Read", "Glob", "Grep", "Bash"]


def test_implement_tools_include_write_edit_bash():
    _, tools = load_stage_agent("implement")
    assert set(["Read", "Glob", "Grep", "Edit", "Write", "Bash"]) == set(tools)


def test_unknown_stage_raises():
    with pytest.raises(ValueError):
        load_stage_agent("nao-existe")


def test_has_stage():
    assert has_stage("plan") and has_stage("implement") and has_stage("review")
    assert not has_stage("validate_ci") and not has_stage("backlog")


def test_build_prompt_review_includes_diff():
    p = build_stage_prompt("review", "T", "d", "/wt", {"diff": "DIFF_MARKER"})
    assert "DIFF_MARKER" in p


def test_build_prompt_implement_fix_lists_findings():
    findings = {"blocks": [{"titulo": "bug X", "arquivo": "a.py", "porque": "y"}], "fixNow": []}
    p = build_stage_prompt("implement", "T", "d", "/wt", {"findings": findings})
    assert "bug X" in p and "commit" in p.lower()


def test_build_stage_options_inclui_snippet_de_autonomia():
    from src.services.stage_runner import build_stage_options
    opts = build_stage_options("implement", "/tmp/wt", "opus-4.8")
    append = opts.system_prompt["append"]
    assert "Operacao autonoma" in append
    assert "needs_human" in append          # o snippet preserva a valvula de escape
    assert opts.model == "claude-opus-4-8[1m]"
    assert opts.permission_mode == "acceptEdits"


def test_build_stage_options_sem_model_usa_default_do_cli():
    from src.services.stage_runner import build_stage_options
    opts = build_stage_options("plan", "/tmp/wt", None)
    assert getattr(opts, "model", None) is None
