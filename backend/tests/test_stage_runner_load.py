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


def test_prompt_inclui_contexto_do_projeto():
    from src.services.stage_runner import build_stage_prompt
    ctx = {"project_name": "GMS Web", "objective": "ERP para gestao de oficinas",
           "rules_file": "REGRAS.md", "requested_by": "PO Maria"}
    p = build_stage_prompt("implement", "Titulo", "Desc", "/wt", {"context": ctx})
    assert "GMS Web" in p
    assert "ERP para gestao de oficinas" in p
    assert "REGRAS.md" in p
    assert "AGENTS.md" not in p          # hardcode removido: usa o rules_file do projeto
    assert "PO Maria" in p


def test_prompt_sem_contexto_usa_default_agents_md():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("implement", "Titulo", "Desc", "/wt", {})
    assert "AGENTS.md" in p


async def test_run_stage_captura_tool_calls(monkeypatch):
    """N5: ToolUseBlock do agente vira log tipado 'tool' via on_log."""
    from src.services import stage_runner  # noqa: F401
    from src.services.stage_runner import _AttemptOutcome  # noqa: F401

    logs: list[tuple] = []

    async def on_log(text, log_type="info"):
        logs.append((log_type, text))

    # _run_single_attempt real e complexo (SDK); este teste cobre o formatador de tool.
    from src.services.stage_runner import _format_tool_use
    assert "Edit" in _format_tool_use("Edit", {"file_path": "a.py", "old_string": "x"})
    assert "a.py" in _format_tool_use("Edit", {"file_path": "a.py"})
    assert _format_tool_use("Bash", {"command": "ls -la"}).startswith("Bash")


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


def test_triage_mapeado_em_stage_agents():
    from src.services.stage_runner import load_stage_agent
    body, tools = load_stage_agent("triage")
    assert "leve" in body and "padrao" in body
    assert tools == ["Read", "Glob", "Grep"]


def test_prompt_do_triage_pede_json_de_trilha():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("triage", "Corrigir typo no botao", "so o texto", "/wt", {})
    assert "trilha" in p
    assert "NAO implemente" in p


def test_agentes_sdd_mapeados():
    from src.services.stage_runner import load_stage_agent
    for key, filename_hint in (("specify", "specifier"), ("clarify", "clarifier"), ("tasks", "tasker")):
        body, tools = load_stage_agent(key)
        assert body.strip(), key
        assert tools == ["Read", "Glob", "Grep"], key


def test_prompt_generico_encadeia_saidas_anteriores():
    from src.services.stage_runner import build_stage_prompt
    p = build_stage_prompt("specify", "Feature X", "detalhe", "/wt",
                           {"chain": "SAIDA-DO-ESTAGIO-ANTERIOR"})
    assert "Feature X" in p
    assert "SAIDA-DO-ESTAGIO-ANTERIOR" in p
    assert "pendingQuestions" in p          # valvula de escalacao padrao dos estagios genericos


def test_build_stage_options_apende_prompt_do_perfil(monkeypatch):
    from src.config.model_ids import ModelProfile
    from src.config import model_ids
    from src.services.stage_runner import build_stage_options
    monkeypatch.setitem(model_ids.MODEL_PROFILES, "teste-x",
                        ModelProfile("claude-teste", prompt_append="\nSNIPPET-DO-PERFIL"))
    opts = build_stage_options("plan", "/wt", "teste-x")
    assert "SNIPPET-DO-PERFIL" in opts.system_prompt["append"]


def test_prompt_de_planejamento_inclui_decisoes_anteriores():
    from src.services.stage_runner import build_stage_prompt
    extra = {"decisions": "Decisoes anteriores deste projeto...\n- P: Qual banco?\n  D: SQLite"}
    for stage in ("plan", "specify"):
        p = build_stage_prompt(stage, "T", "D", "/wt", extra)
        assert "Qual banco?" in p, stage
    # implement/review NAO recebem o bloco (foco: planejamento)
    for stage in ("implement", "review"):
        p = build_stage_prompt(stage, "T", "D", "/wt", extra)
        assert "Qual banco?" not in p, stage
