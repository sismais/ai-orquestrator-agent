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
    # 5 estagios (plan, implement, review, fix-implement, re-review) x (100 in + 50 out)
    assert ex.input_tokens == 500
    assert ex.output_tokens == 250
    assert ex.total_tokens == 750
    assert ex.fix_iterations == 1
    assert "opus-4.8" in (ex.model_used or "")


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
