"""Orquestrador de pipeline (Fase 3b-resto).

O backend dirige o card pelas colunas do workflow (`plan -> implement -> review`), executando
o agente de estagio do DevKit por coluna numa unica worktree reusada. Faz o fix-loop
(review->implement), pausa em ambiguidade/erro (Pause-or-Decide), avanca a coluna do card e
transmite os logs pro board. NAO abre PR nem faz merge (isso e 3c).

Roda em background (o endpoint dispara e retorna na hora). Abre sua propria sessao de DB.
"""

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from ..database import async_session_maker
from ..git_workspace import GitWorkspaceManager
from ..models.card import Card
from ..models.execution import Execution, ExecutionLog, ExecutionStatus
from ..models.project_registry import Project
from ..repositories.activity_repository import ActivityRepository
from ..repositories.card_repository import CardRepository
from ..services.card_ws import card_ws_manager
from ..services.execution_ws import execution_ws_manager
from ..services.findings import (
    detect_needs_human,
    parse_pending_questions,
    parse_review_findings_strict,
    parse_track_verdict,
)
from ..services.runner_service import prepare_worktree
from ..services.stage_runner import (
    build_stage_prompt,
    run_stage as _default_run_stage,
)
from ..services.validate_ci_stage import run_validate_ci
from ..services.workflow_rules import next_active_column

DEFAULT_MAX_ITERATIONS = 4
_LOG_FLUSH_CHARS = 800
TRIAGE_MODEL = "haiku-4.5"  # triagem e barata; recusa cai no fallback do perfil (N1)

# Colunas que o pipeline executa: estagios de agente + validate_ci (git/gh, tratado a parte).
_AGENT_STAGES = ("plan", "implement", "review")

# coluna -> campo do card com o alias de modelo escolhido para a etapa.
_STAGE_MODEL_FIELD = {"plan": "model_plan", "implement": "model_implement", "review": "model_review"}


def _pipeline_handles(col: Optional[str]) -> bool:
    return col in _AGENT_STAGES or col == "validate_ci"


def stage_model_for_column(col: str, card) -> "str | None":
    """Alias do modelo escolhido para a etapa (coluna) corrente, ou None se a coluna nao executa agente por-modelo."""
    field = _STAGE_MODEL_FIELD.get(col)
    return getattr(card, field, None) if field else None


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


def _format_questions(pend: list) -> str:
    """Formata as pendingQuestions do agente num texto legivel para o card."""
    lines = ["O agente precisa da sua decisao para continuar:"]
    for i, q in enumerate(pend, 1):
        if isinstance(q, dict):
            question = q.get("question") or q.get("q") or str(q)
            ctx = q.get("context")
            lines.append(f"{i}. {question}" + (f"\n   ({ctx})" if ctx else ""))
        else:
            lines.append(f"{i}. {q}")
    return "\n".join(lines)


def _first_stage(transitions: dict, current: str) -> Optional[str]:
    """Onde comecar: a propria coluna se o pipeline a trata, senao a proxima ativa."""
    if _pipeline_handles(current):
        return current
    return next_active_column(transitions, current)


async def _broadcast_moved(card: Card, from_col: str, to_col: str) -> None:
    # Serializa o card completo (mesma forma do routes/cards.py) — o front SUBSTITUI o card
    # pelo payload; enviar parcial apagaria titulo/descricao/etc.
    try:
        from ..schemas.card import CardResponse
        card_dict = CardResponse.model_validate(card).model_dump(by_alias=True, mode="json")
    except Exception:  # noqa: BLE001
        card_dict = {"id": card.id, "columnId": to_col}
    try:
        await card_ws_manager.broadcast_card_moved(card.id, from_col, to_col, card_dict)
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
    resume_stage: Optional[str] = None,
    human_answer: Optional[str] = None,
    session_maker=async_session_maker,
    stage_fn=_default_run_stage,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> None:
    """Executa o pipeline do card. Silencioso em falha (marca a Execution e para).

    `resume_stage`/`human_answer`: retomada apos pausa — comeca em `resume_stage` (reusando a
    worktree existente), injetando a resposta humana no prompt da primeira etapa.
    """
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
        stage_context = {
            "project_name": project.name,
            "objective": getattr(project, "objective", None),
            "rules_file": project.rules_file or "AGENTS.md",
            "requested_by": getattr(card, "requested_by", None),
        }
        total_cost = 0.0
        iteration = 0
        plan_text: Optional[str] = None
        tokens = {"input": 0, "output": 0}
        models_used: set[str] = set()

        async def account(res, model_alias: "str | None" = None):
            nonlocal total_cost
            if res is None:
                return
            if res.cost_usd:
                total_cost += float(res.cost_usd)
            u = getattr(res, "usage", None)
            if isinstance(u, dict):
                tokens["input"] += int(u.get("input_tokens") or 0) \
                    + int(u.get("cache_creation_input_tokens") or 0) \
                    + int(u.get("cache_read_input_tokens") or 0)
                tokens["output"] += int(u.get("output_tokens") or 0)
            used = getattr(res, "used_model", None) or model_alias
            if used:
                models_used.add(used)

        def persist_run_stats() -> None:
            execution.input_tokens = tokens["input"] or None
            execution.output_tokens = tokens["output"] or None
            execution.total_tokens = (tokens["input"] + tokens["output"]) or None
            execution.model_used = ",".join(sorted(models_used)) or None
            execution.fix_iterations = iteration
            execution.execution_cost = total_cost or None

        async def finish_pause(reason: str, context: Optional[str], question: Optional[str] = None) -> None:
            await log.event(f"PAUSE: {reason}")
            # a pergunta do agente vira comentario no card (thread de interacao humana)
            q = question or f"{reason}\n\n{context or ''}".strip()
            try:
                await ActivityRepository(s).add_comment(card_id, "agent", q[:1900])
            except Exception:  # noqa: BLE001
                pass
            prev = card.column_id
            moved, err = await repo.move(card_id, "paused")
            await s.commit()
            if not err:
                await _broadcast_moved(card, prev, "paused")
            execution.status = ExecutionStatus.PAUSED
            execution.workflow_stage = execution.workflow_stage  # preserva a etapa onde pausou
            execution.workflow_error = f"{reason} | {context or ''}"[:1900]
            execution.is_active = False
            execution.completed_at = datetime.utcnow()
            persist_run_stats()
            await s.commit()
            try:
                await execution_ws_manager.notify_complete(card_id, "paused", "pipeline", error=reason)
            except Exception:  # noqa: BLE001
                pass

        try:
            # 1) worktree — na retomada reusa a existente (preserva os commits); senao cria pristina
            reuse = bool(resume_stage and card.worktree_path and Path(card.worktree_path).exists())
            if reuse:
                worktree = card.worktree_path
            else:
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
            pending_answer = human_answer  # injetado apenas na primeira etapa da retomada
            col = resume_stage or _first_stage(transitions, card.column_id)

            # Triagem de complexidade (N2): so em run novo partindo do backlog. Advisory:
            # erro/lixo -> padrao (nunca bloqueia); so interrupcao do usuario pausa.
            if resume_stage is None and card.column_id == "backlog":
                await log.event("── triagem: classificando a complexidade ──")
                triage_prompt = build_stage_prompt(
                    "triage", card.title, card.description or "", worktree, {"context": stage_context},
                )
                tri = await stage_fn("triage", worktree, triage_prompt, card_id=card_id, on_log=log,
                                     model=TRIAGE_MODEL)
                await log.flush()
                await account(tri, TRIAGE_MODEL)
                if tri.interrupted:
                    await finish_pause(
                        "interrompido pelo usuario", "O usuario parou a execucao durante a triagem.",
                        question="Você interrompeu o agente. O que devo ajustar ou fazer diferente?",
                    )
                    return
                verdict = parse_track_verdict(tri.text if tri.ok else "")
                track = verdict["trilha"]
                execution.track = track
                await s.commit()
                await log.event(f"── trilha: {track} — {verdict['porque'] or 'default conservador'} ──")
                if track == "leve":
                    if "implement" in transitions.get("backlog", []):
                        col = "implement"
                    else:
                        await log.event("── trilha leve indisponivel no workflow (sem backlog→implement) — seguindo padrao ──")

            # 2) laco de estagios
            while col and _pipeline_handles(col):
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

                # validate_ci: push -> PR draft -> espera CI -> ready_to_merge (git/gh, nao um agente)
                if col == "validate_ci":
                    await log.event("── estagio: validate_ci ──")
                    vres = await run_validate_ci(
                        worktree=worktree, branch=card.branch_name or "", base_branch=base_branch,
                        card=card, project=project, gm=gm, log=log, stage_fn=stage_fn,
                        max_iterations=max_iterations, stage_context=stage_context,
                        account_fn=account,
                        fix_model=stage_model_for_column("implement", card),
                    )
                    if vres["status"] == "pause":
                        await finish_pause(vres["reason"], vres.get("context"), question=vres.get("question"))
                        return
                    if vres.get("pr_url"):
                        execution.result = vres["pr_url"]
                        await s.commit()
                    col = next_active_column(transitions, "validate_ci")  # -> ready_to_merge (para)
                    continue
                await log.event(f"── estagio: {col} ──")

                extra: dict = {"context": stage_context}
                if col == "review":
                    extra["diff"] = await gm.diff_against_base(worktree, base_branch)
                elif col == "implement" and plan_text:
                    extra["plan"] = plan_text
                if pending_answer:
                    extra["human_answer"] = pending_answer
                    pending_answer = None
                prompt = build_stage_prompt(col, card.title, card.description or "", worktree, extra)
                res = await stage_fn(col, worktree, prompt, card_id=card_id, on_log=log,
                                     model=stage_model_for_column(col, card))
                await log.flush()
                await account(res, stage_model_for_column(col, card))
                if res.interrupted:
                    await finish_pause(
                        "interrompido pelo usuario", "O usuario parou a execucao para corrigir o rumo.",
                        question="Você interrompeu o agente. O que devo ajustar ou fazer diferente?",
                    )
                    return
                if not res.ok:
                    await finish_pause(f"erro no estagio {col}", res.error)
                    return
                if not (res.text or "").strip():
                    await finish_pause(
                        f"estagio {col} terminou sem output",
                        "O agente encerrou o turno sem produzir texto — provavel recusa ou turno abortado.",
                    )
                    return

                if col == "plan":
                    pend = parse_pending_questions(res.text)
                    if pend:
                        await finish_pause("plan: pendencias de arquitetura", res.text[:1500],
                                           question=_format_questions(pend))
                        return
                    plan_text = res.text
                    col = next_active_column(transitions, "plan")

                elif col == "implement":
                    nh = detect_needs_human(res.text)
                    if nh:
                        await finish_pause(
                            "implement: needs_human", nh,
                            question=f"O agente precisa da sua decisao para continuar:\n\n{nh}",
                        )
                        return
                    await gm.commit_all(worktree, f"wip: {card.title[:60]}")
                    col = next_active_column(transitions, "implement")

                elif col == "review":
                    f = parse_review_findings_strict(res.text)
                    if f is None:
                        # falha-fechada: reviewer sem JSON re-explica o contrato e tenta 1x (A2)
                        await log.event("review sem JSON parseavel — re-pedindo o veredito")
                        retry_prompt = prompt + (
                            "\n\nIMPORTANTE: sua resposta DEVE terminar com o JSON "
                            '{"blocks": [...], "fixNow": [...], "suggestions": [...]} '
                            "(arrays vazios se o diff estiver aprovado). "
                            "Nao ha veredito valido sem esse JSON."
                        )
                        res = await stage_fn("review", worktree, retry_prompt, card_id=card_id, on_log=log,
                                             model=stage_model_for_column("review", card))
                        await log.flush()
                        await account(res, stage_model_for_column("review", card))
                        if res.interrupted:
                            await finish_pause(
                                "interrompido pelo usuario",
                                "O usuario parou a execucao para corrigir o rumo.",
                                question="Você interrompeu o agente. O que devo ajustar ou fazer diferente?",
                            )
                            return
                        if not res.ok:
                            await finish_pause("erro no re-pedido do review", res.error)
                            return
                        f = parse_review_findings_strict(res.text)
                        if f is None:
                            await finish_pause(
                                "review sem veredito parseavel", (res.text or "")[:1500],
                                question=("O revisor nao devolveu o JSON de achados apos 2 tentativas. "
                                          "Como devo proceder?"),
                            )
                            return
                    blocking = len(f["blocks"]) + len(f["fixNow"])
                    if blocking > 0:
                        if iteration >= max_iterations:
                            await finish_pause(
                                f"review nao convergiu apos {iteration} iteracoes", json.dumps(f)[:1500],
                                question=(
                                    f"A revisao nao convergiu apos {iteration} tentativas de correcao. "
                                    "Como devo proceder? (ex.: aceitar como esta, priorizar um achado, mudar a abordagem)"
                                ),
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
                            "implement", card.title, card.description or "", worktree,
                            {"findings": f, "context": stage_context},
                        )
                        fix_res = await stage_fn("implement", worktree, fix_prompt, card_id=card_id, on_log=log,
                                                 model=stage_model_for_column("implement", card))
                        await log.flush()
                        await account(fix_res, stage_model_for_column("implement", card))
                        if fix_res.interrupted:
                            await finish_pause(
                                "interrompido pelo usuario", "O usuario parou a correcao.",
                                question="Você interrompeu. O que devo ajustar?",
                            )
                            return
                        if not fix_res.ok:
                            await finish_pause("erro no fix-loop", fix_res.error)
                            return
                        if not (fix_res.text or "").strip():
                            await finish_pause("fix-loop terminou sem output",
                                               "O agente encerrou o turno sem produzir texto.")
                            return
                        nh = detect_needs_human(fix_res.text)
                        if nh:
                            await finish_pause("fix-loop: needs_human", nh)
                            return
                        await gm.commit_all(worktree, f"fix: {card.title[:50]} #{iteration}")
                        col = "review"  # re-revisa no topo do laco
                        continue
                    col = next_active_column(transitions, "review")  # -> validate_ci

            # 3) parada limpa na fronteira (ex.: ready_to_merge): avanca e encerra
            if col and not _pipeline_handles(col) and card.column_id != col:
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
            persist_run_stats()
            await s.commit()
            try:
                await execution_ws_manager.notify_complete(card_id, "success", "pipeline")
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001 — rede de seguranca: run orfao nunca mais (A1)
            print(f"[pipeline] erro interno:\n{traceback.format_exc()}")
            try:
                await finish_pause("erro interno do orquestrador", str(e))
            except Exception as e2:  # noqa: BLE001 — ultimo recurso: marca a Execution direto
                print(f"[pipeline] finish_pause falhou apos erro interno: {e2!r}")
                try:
                    await s.rollback()
                except Exception:  # noqa: BLE001
                    pass
                execution.status = ExecutionStatus.ERROR
                execution.workflow_error = f"erro interno: {e} | finish_pause: {e2}"[:1900]
                execution.is_active = False
                execution.completed_at = datetime.utcnow()
                await s.commit()
