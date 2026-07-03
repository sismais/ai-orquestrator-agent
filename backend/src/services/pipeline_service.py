"""Orquestrador de pipeline (Fase 3b-resto).

O backend dirige o card pelas colunas do workflow (`plan -> implement -> review`), executando
o agente de estagio do DevKit por coluna numa unica worktree reusada. Faz o fix-loop
(review->implement), pausa em ambiguidade/erro (Pause-or-Decide), avanca a coluna do card e
transmite os logs pro board. NAO abre PR nem faz merge (isso e 3c).

Roda em background (o endpoint dispara e retorna na hora). Abre sua propria sessao de DB.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from ..database import async_session_maker
from ..git_workspace import GitWorkspaceManager
from ..models.card import Card
from ..models.execution import Execution, ExecutionLog, ExecutionStatus
from ..models.project_registry import Project
from ..repositories.card_repository import CardRepository
from ..services.card_ws import card_ws_manager
from ..services.execution_ws import execution_ws_manager
from ..services.findings import (
    detect_needs_human,
    parse_pending_questions,
    parse_review_findings,
)
from ..services.runner_service import prepare_worktree
from ..services.stage_runner import (
    build_stage_prompt,
    has_stage,
    run_stage as _default_run_stage,
)
from ..services.workflow_rules import next_active_column

DEFAULT_MAX_ITERATIONS = 4
_LOG_FLUSH_CHARS = 800


class _LogSink:
    """Acumula texto do agente e faz flush em lote: persiste ExecutionLog + transmite por WS.

    Tudo awaited no mesmo coroutine do orquestrador -> ordem preservada (sequence monotonico).
    """

    def __init__(self, session, execution_id: str, card_id: str):
        self.s = session
        self.eid = execution_id
        self.cid = card_id
        self._buf: list[str] = []
        self._size = 0
        self._seq = 0

    async def __call__(self, text: str) -> None:
        self._buf.append(text)
        self._size += len(text)
        if self._size >= _LOG_FLUSH_CHARS:
            await self.flush()

    async def flush(self) -> None:
        if not self._buf:
            return
        chunk = "".join(self._buf)
        self._buf.clear()
        self._size = 0
        await self._emit("info", chunk)

    async def event(self, text: str) -> None:
        """Marcador de estagio (drena o buffer antes p/ manter a ordem)."""
        await self.flush()
        await self._emit("system", text)

    async def _emit(self, log_type: str, content: str) -> None:
        self.s.add(ExecutionLog(
            execution_id=self.eid, type=log_type, content=content, sequence=self._seq,
        ))
        self._seq += 1
        await self.s.commit()
        try:
            await execution_ws_manager.notify_log(self.cid, log_type, content)
        except Exception:  # noqa: BLE001 — WS nao pode derrubar o pipeline
            pass


def _first_stage(transitions: dict, current: str) -> Optional[str]:
    """Onde comecar: a propria coluna se ja e um estagio, senao a proxima ativa."""
    if has_stage(current):
        return current
    return next_active_column(transitions, current)


async def _broadcast_moved(card: Card, from_col: str, to_col: str) -> None:
    try:
        await card_ws_manager.broadcast_card_moved(
            card.id, from_col, to_col, {"id": card.id, "columnId": to_col},
        )
    except Exception:  # noqa: BLE001
        pass


async def create_execution(session, card_id: str, title: Optional[str] = None) -> str:
    """Cria a Execution(running) e devolve o id (usado pelo endpoint p/ responder na hora)."""
    prior = (await session.execute(
        select(Execution).where(Execution.card_id == card_id, Execution.is_active == True)  # noqa: E712
    )).scalars().all()
    for ex in prior:
        ex.is_active = False
    execution = Execution(
        card_id=card_id, status=ExecutionStatus.RUNNING, command="pipeline",
        title=title, is_active=True,
    )
    session.add(execution)
    await session.flush()
    exec_id = execution.id
    await session.commit()
    return exec_id


async def run_pipeline(
    project_id: str,
    card_id: str,
    *,
    execution_id: Optional[str] = None,
    session_maker=async_session_maker,
    stage_fn=_default_run_stage,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> None:
    """Executa o pipeline do card. Silencioso em falha (marca a Execution e para)."""
    async with session_maker() as s:
        project = (await s.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        repo = CardRepository(s)
        card = await repo.get_by_id(card_id)
        if not project or not card:
            return

        if execution_id:
            execution = (await s.execute(
                select(Execution).where(Execution.id == execution_id)
            )).scalar_one_or_none()
        else:
            execution = None
        if execution is None:
            exec_id = await create_execution(s, card_id, card.title)
            execution = (await s.execute(
                select(Execution).where(Execution.id == exec_id)
            )).scalar_one_or_none()
        else:
            exec_id = execution.id

        log = _LogSink(s, exec_id, card_id)
        gm = GitWorkspaceManager(project.path)
        base_branch = project.base_branch or "main"
        total_cost = 0.0

        async def account(res):
            nonlocal total_cost
            if res is not None and res.cost_usd:
                total_cost += float(res.cost_usd)

        async def finish_pause(reason: str, context: Optional[str]) -> None:
            await log.event(f"PAUSE: {reason}")
            prev = card.column_id
            moved, err = await repo.move(card_id, "paused")
            await s.commit()
            if not err:
                await _broadcast_moved(card, prev, "paused")
            execution.status = ExecutionStatus.PAUSED
            execution.workflow_error = f"{reason} | {context or ''}"[:1900]
            execution.is_active = False
            execution.completed_at = datetime.utcnow()
            execution.execution_cost = total_cost or None
            await s.commit()
            try:
                await execution_ws_manager.notify_complete(card_id, "paused", "pipeline", error=reason)
            except Exception:  # noqa: BLE001
                pass

        # 1) worktree (reuso ao longo do card)
        try:
            wt = await prepare_worktree(project.path, base_branch, card_id)
        except Exception as e:  # noqa: BLE001
            await finish_pause("falha ao preparar worktree", str(e))
            return
        if not wt.success or not wt.worktree_path:
            await finish_pause("falha ao criar worktree", wt.error)
            return
        card.worktree_path = wt.worktree_path
        card.branch_name = wt.branch_name
        await s.commit()
        worktree = wt.worktree_path

        transitions = await repo._get_transitions_for_card(card)
        iteration = 0
        col = _first_stage(transitions, card.column_id)

        # 2) laco de estagios
        while col and has_stage(col):
            prev = card.column_id
            moved, err = await repo.move(card_id, col)
            await s.commit()
            if err:
                await finish_pause(f"transicao invalida para {col}", err)
                return
            card = moved
            await _broadcast_moved(card, prev, col)
            execution.workflow_stage = col
            await s.commit()
            await log.event(f"── estagio: {col} ──")

            extra: dict = {}
            if col == "review":
                extra["diff"] = await gm.diff_against_base(worktree, base_branch)
            prompt = build_stage_prompt(col, card.title, card.description or "", worktree, extra)
            res = await stage_fn(col, worktree, prompt, on_log=log)
            await log.flush()
            await account(res)
            if not res.ok:
                await finish_pause(f"erro no estagio {col}", res.error)
                return

            if col == "plan":
                if parse_pending_questions(res.text):
                    await finish_pause("plan: pendencias de arquitetura", res.text[:1500])
                    return
                col = next_active_column(transitions, "plan")

            elif col == "implement":
                nh = detect_needs_human(res.text)
                if nh:
                    await finish_pause("implement: needs_human", nh)
                    return
                await gm.commit_all(worktree, f"wip: {card.title[:60]}")
                col = next_active_column(transitions, "implement")

            elif col == "review":
                f = parse_review_findings(res.text)
                blocking = len(f["blocks"]) + len(f["fixNow"])
                if blocking > 0:
                    if iteration >= max_iterations:
                        await finish_pause(
                            f"review nao convergiu apos {iteration} iteracoes", json.dumps(f)[:1500]
                        )
                        return
                    iteration += 1
                    prev = card.column_id
                    moved, err = await repo.move(card_id, "implement")
                    await s.commit()
                    if err:
                        await finish_pause("fix-loop: transicao invalida", err)
                        return
                    card = moved
                    await _broadcast_moved(card, prev, "implement")
                    await log.event(f"── fix-loop #{iteration}: implement ──")
                    fix_prompt = build_stage_prompt(
                        "implement", card.title, card.description or "", worktree, {"findings": f},
                    )
                    fix_res = await stage_fn("implement", worktree, fix_prompt, on_log=log)
                    await log.flush()
                    await account(fix_res)
                    if not fix_res.ok:
                        await finish_pause("erro no fix-loop", fix_res.error)
                        return
                    nh = detect_needs_human(fix_res.text)
                    if nh:
                        await finish_pause("fix-loop: needs_human", nh)
                        return
                    await gm.commit_all(worktree, f"fix: {card.title[:50]} #{iteration}")
                    col = "review"  # re-revisa no topo do laco
                    continue
                col = next_active_column(transitions, "review")  # -> validate_ci (sem handler) -> para

        # 3) parada limpa na fronteira (ex.: validate_ci = handoff 3c): avanca e encerra
        if col and not has_stage(col) and card.column_id != col:
            prev = card.column_id
            moved, err = await repo.move(card_id, col)
            await s.commit()
            if not err:
                card = moved
                await _broadcast_moved(card, prev, col)

        await log.event(f"── pipeline concluido (parou em: {card.column_id}) ──")
        execution.status = ExecutionStatus.SUCCESS
        execution.is_active = False
        execution.completed_at = datetime.utcnow()
        execution.execution_cost = total_cost or None
        await s.commit()
        try:
            await execution_ws_manager.notify_complete(card_id, "success", "pipeline")
        except Exception:  # noqa: BLE001
            pass
