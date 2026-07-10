import inspect

import pytest
import src.models  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import Base
from src.git_workspace import GitWorkspaceManager, WorktreeResult
from src.models.execution import Execution
from src.models.project_registry import Project
from src.repositories.card_repository import CardRepository
from src.schemas.card import CardCreate
from src.services import pipeline_service
from src.services.stage_runner import StageResult


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield m
    await engine.dispose()


@pytest.fixture(autouse=True)
def stub_git(monkeypatch, tmp_path):
    """Neutraliza git/worktree reais no unit test do orquestrador."""
    async def fake_prepare(project_path, base_branch, card_id):
        wt = tmp_path / f"wt-{card_id[:8]}"
        wt.mkdir(exist_ok=True)
        return WorktreeResult(success=True, worktree_path=str(wt), branch_name="agent/test")

    async def fake_commit(self, worktree_path, message, exclude=None):
        return True, "ok"

    async def fake_diff(self, worktree_path, base_branch):
        return "diff --git a/x b/x\n+mudou"

    async def fake_validate_ci(**kwargs):
        return {"status": "ok", "pr_url": "http://pr/1"}

    monkeypatch.setattr(pipeline_service, "prepare_worktree", fake_prepare)
    monkeypatch.setattr(pipeline_service, "run_validate_ci", fake_validate_ci)
    monkeypatch.setattr(GitWorkspaceManager, "commit_all", fake_commit)
    monkeypatch.setattr(GitWorkspaceManager, "diff_against_base", fake_diff)


def make_stage_fn(script):
    """script: {stage_key: [texts...]} — devolvidos por chamada; default benigno."""
    counts: dict[str, int] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if on_log:
            r = on_log(f"[{stage_key}] trabalhando...\n")
            if inspect.isawaitable(r):
                await r
        idx = counts.get(stage_key, 0)
        counts[stage_key] = idx + 1
        texts = script.get(stage_key)
        text = texts[min(idx, len(texts) - 1)] if texts else f"{stage_key} ok"
        return StageResult(ok=True, text=text, cost_usd=0.01)

    return fake, counts


async def _make_project_card(maker):
    async with maker() as s:
        s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev", base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X"), project_id="p1")
        await s.commit()
        return card.id


async def _card_column(maker, card_id):
    async with maker() as s:
        c = await CardRepository(s).get_by_id(card_id)
        return c.column_id


async def _last_execution(maker, card_id):
    from sqlalchemy import select
    async with maker() as s:
        return (await s.execute(
            select(Execution).where(Execution.card_id == card_id).order_by(Execution.started_at.desc())
        )).scalars().first()


async def test_happy_path_lands_on_validate_ci(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": ['{"blocks":[],"fixNow":[],"suggestions":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "success"
    assert counts.get("plan") == 1 and counts.get("implement") == 1 and counts.get("review") == 1


async def test_fix_loop_runs_implement_twice(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": [
        '{"blocks":[{"titulo":"bug","arquivo":"a.py:1","porque":"x"}],"fixNow":[]}',
        '{"blocks":[],"fixNow":[]}',
    ]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    assert counts.get("implement") == 2 and counts.get("review") == 2


async def test_non_convergence_pauses(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": ['{"blocks":[{"titulo":"sempre"}],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake, max_iterations=2)

    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "paused"


async def test_needs_human_on_implement_pauses_before_review(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"implement": ["status: needs_human — migration arriscada"]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("review") is None  # nem chegou em review


async def test_pending_questions_on_plan_pauses(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"plan": ['{"pendingQuestions":[{"question":"qual banco?"}]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("implement") is None


async def test_resume_starts_at_stage_with_answer(maker):
    card_id = await _make_project_card(maker)
    # simula card pausado (backlog -> paused e transicao valida no config dev)
    async with maker() as s:
        await CardRepository(s).move(card_id, "paused")
        await s.commit()
    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text, cost_usd=0.0)

    await pipeline_service.run_pipeline(
        "p1", card_id, session_maker=maker, stage_fn=fake,
        resume_stage="implement", human_answer="use a lib X",
    )
    assert "plan" not in seen                       # retomou sem refazer o plan
    assert seen.get("implement")                    # comecou no implement
    assert "use a lib X" in seen["implement"][0]    # resposta humana injetada no prompt
    assert await _card_column(maker, card_id) == "ready_to_merge"


async def test_estagio_sem_output_pausa(maker):
    """Turno vazio (ok=True, text='') nao pode contar como estagio concluido (A2)."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"plan": [""]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("implement") is None
    ex = await _last_execution(maker, card_id)
    assert "sem output" in (ex.workflow_error or "")


async def test_interrupt_pauses_card(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        # simula Stop no implement
        if stage_key == "implement":
            return StageResult(ok=True, text="", interrupted=True)
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "paused"


async def test_pause_writes_agent_comment(maker):
    from sqlalchemy import select as _select
    from src.models.activity_log import ActivityLog, ActivityType
    card_id = await _make_project_card(maker)
    fake, _ = make_stage_fn({"plan": ['{"pendingQuestions":[{"question":"qual banco?"}]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    async with maker() as s:
        acts = (await s.execute(
            _select(ActivityLog).where(
                ActivityLog.card_id == card_id,
                ActivityLog.activity_type == ActivityType.COMMENTED,
            )
        )).scalars().all()
    assert any(a.user_id == "agent" and "qual banco" in (a.description or "") for a in acts)


async def test_logs_persisted(maker):
    from sqlalchemy import select
    from src.models.execution import ExecutionLog
    card_id = await _make_project_card(maker)
    fake, _ = make_stage_fn({"review": ['{"blocks":[],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    async with maker() as s:
        logs = (await s.execute(select(ExecutionLog))).scalars().all()
    assert len(logs) > 0


async def test_review_sem_json_nao_aprova_o_diff(maker):
    """Review que nunca devolve JSON: re-pede 1x e depois PAUSA (falha-fechada, A2)."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": ["parece tudo certo! aprovado."]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "paused"      # NAO ready_to_merge
    assert counts.get("review") == 2                            # pediu de novo antes de pausar
    ex = await _last_execution(maker, card_id)
    assert "veredito" in (ex.workflow_error or "")


async def test_review_json_na_segunda_tentativa_aprova(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({"review": [
        "sem json aqui",
        '{"blocks":[],"fixNow":[],"suggestions":[]}',
    ]})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    assert counts.get("review") == 2


async def test_tokens_modelos_e_iteracoes_persistidos(maker):
    """A5: usage do ResultMessage + modelos por etapa + fix_iterations ficam na Execution."""
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        text = ('{"blocks":[{"titulo":"x"}],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok")
        # segunda revisao aprova
        if stage_key == "review" and fake.review_calls > 0:
            text = '{"blocks":[],"fixNow":[]}'
        if stage_key == "review":
            fake.review_calls += 1
        return StageResult(ok=True, text=text, cost_usd=0.01,
                           usage={"input_tokens": 100, "output_tokens": 50})
    fake.review_calls = 0

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    ex = await _last_execution(maker, card_id)
    # 6 chamadas (triage, plan, implement, review, fix-implement, re-review) x (100 in + 50 out)
    # — N2 adicionou a triagem no inicio de todo run novo partindo do backlog.
    assert ex.input_tokens == 600
    assert ex.output_tokens == 300
    assert ex.total_tokens == 900
    assert ex.fix_iterations == 1
    assert "opus-4.8" in (ex.model_used or "")


async def test_prompt_do_estagio_recebe_contexto_do_projeto(maker):
    """A4: objetivo do projeto e solicitante chegam ao prompt de todos os estagios."""
    async with maker() as s:
        from sqlalchemy import select as _sel
        p = (await s.execute(_sel(Project).where(Project.id == "p1"))).scalar_one_or_none()
        if p is None:
            s.add(Project(id="p1", name="proj", path="/tmp/proj", workflow_id="dev",
                          base_branch="main", objective="ERP de gestao"))
        else:
            p.objective = "ERP de gestao"
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa X", requestedBy="CEO"), project_id="p1")
        await s.commit()
        card_id = card.id

    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    for stage in ("plan", "implement", "review"):
        assert "ERP de gestao" in seen[stage][0], stage
        assert "CEO" in seen[stage][0], stage


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


async def test_triagem_leve_pula_o_plan(maker):
    """N2: router diz 'leve' -> pipeline comeca no implement (sem plan) e registra a trilha."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ['{"trilha": "leve", "porque": "typo de um arquivo"}'],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert await _card_column(maker, card_id) == "ready_to_merge"
    assert counts.get("triage") == 1
    assert counts.get("plan") is None            # pulou o plan
    assert counts.get("implement") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "leve"


async def test_triagem_padrao_segue_fluxo_completo(maker):
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ['{"trilha": "padrao", "porque": "feature com arquitetura"}'],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)

    assert counts.get("plan") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_nao_parseavel_cai_em_padrao(maker):
    """Triagem e advisory: lixo/erro nunca bloqueia — default padrao."""
    card_id = await _make_project_card(maker)
    fake, counts = make_stage_fn({
        "triage": ["nao sei classificar isso"],
        "review": ['{"blocks":[],"fixNow":[],"suggestions":[]}'],
    })
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert counts.get("plan") == 1
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_com_erro_nao_pausa_cai_em_padrao(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "triage":
            return StageResult(ok=False, error="explodiu na triagem")
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "ready_to_merge"   # nao pausou
    ex = await _last_execution(maker, card_id)
    assert ex.track == "padrao"


async def test_triagem_interrompida_pausa(maker):
    card_id = await _make_project_card(maker)

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        if stage_key == "triage":
            return StageResult(ok=True, text="", interrupted=True)
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"


async def test_retomada_nao_re_tria(maker):
    """Resume (resume_stage) NUNCA roda triagem de novo."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        await CardRepository(s).move(card_id, "paused")
        await s.commit()
    fake, counts = make_stage_fn({"review": ['{"blocks":[],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake,
                                        resume_stage="implement", human_answer="segue")
    assert counts.get("triage") is None
    assert await _card_column(maker, card_id) == "ready_to_merge"


async def test_card_fora_do_backlog_nao_tria(maker):
    """Card posicionado manualmente (override humano) nao passa por triagem."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        await CardRepository(s).move(card_id, "plan")
        await s.commit()
    fake, counts = make_stage_fn({"review": ['{"blocks":[],"fixNow":[]}']})
    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert counts.get("triage") is None
    assert counts.get("plan") == 1


async def test_excecao_inesperada_pausa_o_card(maker):
    """Excecao fora do stage_fn nao pode deixar a Execution RUNNING orfa (A1)."""
    card_id = await _make_project_card(maker)

    async def boom(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        raise RuntimeError("explodiu por dentro")

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=boom)

    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "paused"
    assert ex.is_active is False
    assert "erro interno" in (ex.workflow_error or "")
    assert "explodiu por dentro" in (ex.workflow_error or "")


async def _make_project_card_com_workflow(maker, columns, transitions, workflow_id="custom"):
    """Projeto com workflow CUSTOM + card. Reusa o padrao de _make_project_card."""
    from src.models.workflow import Workflow
    async with maker() as s:
        s.add(Workflow(id=workflow_id, name="Custom", columns=columns, transitions=transitions))
        s.add(Project(id="p2", name="proj2", path="/tmp/proj2", workflow_id=workflow_id,
                      base_branch="main"))
        repo = CardRepository(s)
        card = await repo.create(CardCreate(title="Tarefa Y"), project_id="p2")
        await s.commit()
        return card.id


_SDD_COLUMNS = [
    {"key": "backlog", "label": "Backlog", "order": 0, "agentKey": None, "isPausedState": False, "isTerminal": False},
    {"key": "spec", "label": "Spec", "order": 1, "agentKey": "specify", "isPausedState": False, "isTerminal": False},
    {"key": "implement", "label": "Implement", "order": 2, "agentKey": "implement", "isPausedState": False, "isTerminal": False},
    {"key": "review", "label": "Review", "order": 3, "agentKey": "review", "isPausedState": False, "isTerminal": False},
    {"key": "entregue", "label": "Entregue", "order": 4, "agentKey": None, "isPausedState": False, "isTerminal": True},
    {"key": "paused", "label": "Paused", "order": 5, "agentKey": None, "isPausedState": True, "isTerminal": False},
]
_SDD_TRANSITIONS = {
    "backlog": ["spec", "paused"],
    "spec": ["implement", "paused"],
    "implement": ["review", "paused"],
    "review": ["entregue", "implement", "paused"],
    "entregue": [],
    "paused": ["spec", "implement", "review"],
}


async def test_workflow_custom_executa_coluna_spec(maker):
    """N4: coluna 'spec' (agentKey specify) EXECUTA e encadeia a saida para o implement."""
    card_id = await _make_project_card_com_workflow(maker, _SDD_COLUMNS, _SDD_TRANSITIONS)
    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        if stage_key == "review":
            return StageResult(ok=True, text='{"blocks":[],"fixNow":[]}')
        if stage_key == "specify":
            return StageResult(ok=True, text="SPEC-GERADA-PELO-SPECIFIER")
        return StageResult(ok=True, text=f"{stage_key} ok")

    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)

    assert "specify" in seen                                   # a coluna spec executou
    assert "SPEC-GERADA-PELO-SPECIFIER" in seen["implement"][0]  # saida encadeada ao implement
    assert await _card_column(maker, card_id) == "entregue"    # fronteira custom (agentKey None)


async def test_workflow_custom_pausa_em_pending_questions_de_estagio_generico(maker):
    card_id = await _make_project_card_com_workflow(maker, _SDD_COLUMNS, _SDD_TRANSITIONS,
                                                    workflow_id="custom2")
    fake, counts = make_stage_fn({
        "specify": ['{"pendingQuestions":[{"question":"qual regra de negocio?"}]}'],
    })
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    assert counts.get("implement") is None


async def test_agentkey_desconhecido_pausa_com_motivo(maker):
    cols = [
        {"key": "backlog", "label": "B", "order": 0, "agentKey": None, "isPausedState": False, "isTerminal": False},
        {"key": "magica", "label": "M", "order": 1, "agentKey": "inexistente", "isPausedState": False, "isTerminal": False},
        {"key": "paused", "label": "P", "order": 2, "agentKey": None, "isPausedState": True, "isTerminal": False},
    ]
    trans = {"backlog": ["magica", "paused"], "magica": ["paused"], "paused": ["magica"]}
    card_id = await _make_project_card_com_workflow(maker, cols, trans, workflow_id="custom3")
    fake, counts = make_stage_fn({})
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "paused"
    ex = await _last_execution(maker, card_id)
    assert "agentKey" in (ex.workflow_error or "")


async def test_pausa_vai_para_coluna_de_pausa_do_config(maker):
    """N4-review: o DESTINO da pausa vem do isPausedState do config (nao do literal 'paused')."""
    cols = [
        {"key": "backlog", "label": "B", "order": 0, "agentKey": None, "isPausedState": False, "isTerminal": False},
        {"key": "spec", "label": "S", "order": 1, "agentKey": "specify", "isPausedState": False, "isTerminal": False},
        {"key": "entregue", "label": "E", "order": 2, "agentKey": None, "isPausedState": False, "isTerminal": True},
        {"key": "esperando", "label": "Esperando humano", "order": 3, "agentKey": None, "isPausedState": True, "isTerminal": False},
    ]
    trans = {
        "backlog": ["spec", "esperando"],
        "spec": ["entregue", "esperando"],
        "entregue": [],
        "esperando": ["spec"],
    }
    card_id = await _make_project_card_com_workflow(maker, cols, trans, workflow_id="custom4")
    fake, counts = make_stage_fn({
        "specify": ['{"pendingQuestions":[{"question":"qual regra?"}]}'],
    })
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake)
    assert await _card_column(maker, card_id) == "esperando"   # pausou na coluna do config
    ex = await _last_execution(maker, card_id)
    assert ex.status.value == "paused"


async def test_resume_com_etapa_inexistente_no_workflow_segue_do_inicio_ativo(maker):
    """N4-review: resume_stage que nao existe no workflow custom nao termina SUCCESS no-op."""
    card_id = await _make_project_card_com_workflow(maker, _SDD_COLUMNS, _SDD_TRANSITIONS,
                                                    workflow_id="custom5")
    async with maker() as s:
        await CardRepository(s).move(card_id, "paused")   # simula card pausado
        await s.commit()
    fake, counts = make_stage_fn({
        "review": ['{"blocks":[],"fixNow":[]}'],
    })
    await pipeline_service.run_pipeline("p2", card_id, session_maker=maker, stage_fn=fake,
                                        resume_stage="plan", human_answer="segue")
    assert counts.get("specify") == 1                          # retomou da primeira coluna ativa
    assert await _card_column(maker, card_id) == "entregue"    # e foi ate o fim


async def test_decisoes_anteriores_chegam_ao_prompt_do_plan(maker):
    """N3: decisoes de cards passados do MESMO projeto entram no prompt de planejamento."""
    card_id = await _make_project_card(maker)
    async with maker() as s:
        from src.repositories.decision_repository import DecisionRepository
        await DecisionRepository(s).add(project_id="p1", card_id="outro-card",
                                        question="Qual ORM?", decision="SQLAlchemy 2 async",
                                        source="human", stage="plan")
        await s.commit()

    seen: dict[str, list] = {}

    async def fake(stage_key, worktree, prompt, card_id=None, on_log=None, model=None):
        seen.setdefault(stage_key, []).append(prompt)
        text = '{"blocks":[],"fixNow":[]}' if stage_key == "review" else f"{stage_key} ok"
        return StageResult(ok=True, text=text)

    await pipeline_service.run_pipeline("p1", card_id, session_maker=maker, stage_fn=fake)
    assert "SQLAlchemy 2 async" in seen["plan"][0]
    assert "SQLAlchemy 2 async" not in seen["implement"][0]
