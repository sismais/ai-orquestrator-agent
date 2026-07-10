"""Orquestrador de pipeline (Fase 3b-resto).

O backend dirige o card pelas colunas do workflow (`plan -> implement -> review`), executando
o agente de estagio do DevKit por coluna numa unica worktree reusada. Faz o fix-loop
(review->implement), pausa em ambiguidade/erro (Pause-or-Decide), avanca a coluna do card e
transmite os logs pro board. NAO abre PR nem faz merge (isso e 3c).

Roda em background (o endpoint dispara e retorna na hora). Abre sua propria sessao de DB.
"""

import asyncio
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
from ..repositories.decision_repository import DecisionRepository, format_decisions_block
from ..services.card_ws import card_ws_manager
from ..services.execution_ws import execution_ws_manager
from ..services.findings import (
    detect_needs_human,
    parse_clarifier_output,
    parse_pending_questions,
    parse_review_findings_strict,
    parse_track_verdict,
)
from ..services.runner_service import prepare_worktree
from ..services.stage_runner import (
    build_stage_prompt,
    has_stage,
    run_stage as _default_run_stage,
)
from ..services.validate_ci_stage import run_validate_ci
from ..services.workflow_rules import next_active_column, pause_columns_from

DEFAULT_MAX_ITERATIONS = 4
_LOG_FLUSH_CHARS = 800
TRIAGE_MODEL = "haiku-4.5"  # triagem e barata; recusa cai no fallback do perfil (N1)

# agentKey -> campo do card com o alias de modelo escolhido para a etapa.
# Estagios SDD genericos usam o modelo do plan (mesma natureza: planejamento read-only).
_STAGE_MODEL_FIELD = {
    "plan": "model_plan", "specify": "model_plan", "clarify": "model_plan", "tasks": "model_plan",
    "implement": "model_implement", "review": "model_review",
}

# agentKey do handler git/gh (nao e um agente): normaliza hifen/underscore do config.
_VALIDATE_CI_KEYS = {"validate-ci", "validate_ci"}


def _agent_key_for(col: Optional[str], columns: list) -> Optional[str]:
    """agentKey da coluna no config (None = fronteira/manual)."""
    for c in columns or []:
        if c.get("key") == col:
            return c.get("agentKey")
    return None


def _pipeline_handles(col: Optional[str], columns: list) -> bool:
    return bool(col) and _agent_key_for(col, columns) is not None


def stage_model_for_agent(agent_key: str, card) -> "str | None":
    """Alias do modelo escolhido para o agentKey da etapa corrente, ou None se a etapa nao tem modelo por-card."""
    field = _STAGE_MODEL_FIELD.get(agent_key)
    return getattr(card, field, None) if field else None


# Compat (pre-N4): o nome antigo consultava por coluna; hoje coluna do seed dev == agentKey.
stage_model_for_column = stage_model_for_agent


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
        # Serializa os writes (persist+WS) na sessao do pipeline: o handler do send_to_user
        # (N5) pode interleaver com o drain de texto do receive_response. Cuidado com
        # re-entrancia: flush/event chamam _emit_locked (ja dentro do lock); _emit publico
        # pega o lock — nunca chame _emit de dentro de flush/event.
        self._lock = asyncio.Lock()

    async def __call__(self, text: str, log_type: str = "info") -> None:
        if log_type != "info":
            # tool/progress: drena o buffer de texto e emite imediatamente (ordem preservada,
            # sem esperar o buffer de 800 chars de texto).
            await self.flush()
            await self._emit(log_type, text)
            return
        self._buf.append(text)
        self._size += len(text)
        if self._size >= _LOG_FLUSH_CHARS:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self._buf:
                return
            chunk = "".join(self._buf)
            self._buf.clear()
            self._size = 0
            await self._emit_locked("info", chunk)

    async def event(self, text: str) -> None:
        """Marcador de estagio (drena o buffer antes p/ manter a ordem)."""
        await self.flush()
        async with self._lock:
            await self._emit_locked("system", text)

    async def _emit(self, log_type: str, content: str) -> None:
        async with self._lock:
            await self._emit_locked(log_type, content)

    async def _emit_locked(self, log_type: str, content: str) -> None:
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


def _first_stage(transitions: dict, current: str, columns: list) -> Optional[str]:
    """Onde comecar: a propria coluna se o pipeline a trata, senao a proxima ativa."""
    if _pipeline_handles(current, columns):
        return current
    return next_active_column(transitions, current, pause_columns_from(columns))


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
        # Workflow do card (N4): colunas+transicoes e regras de pausa vem do config.
        # Carregado ANTES de finish_pause: o destino da pausa e a coluna isPausedState do config.
        columns, transitions = await repo._get_workflow_for_card(card)
        pause_cols = pause_columns_from(columns)
        pause_col = next((c["key"] for c in columns if c.get("isPausedState")), "paused")
        # Memoria de decisoes (N3): carregada UMA vez; reinjetada nos prompts de planejamento
        # e consultada pelo gate de escalacao antes de acionar o humano. Best-effort: uma
        # linha de memoria corrompida NUNCA pode orfanar o run nem quebrar runs futuros.
        try:
            decisions_block = format_decisions_block(
                await DecisionRepository(s).recent_for_project(project_id, limit=10)
            )
        except Exception:  # noqa: BLE001
            print(f"[pipeline] memoria de decisoes ilegivel (seguindo sem o bloco):\n{traceback.format_exc()}")
            decisions_block = ""
        total_cost = 0.0
        iteration = 0
        chain_parts: list[str] = []  # saidas dos estagios genericos, encadeadas ate o implement
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
            moved, err = await repo.move(card_id, pause_col)
            await s.commit()
            if err:
                await log.event(f"pausa: card nao movido ({err})")
            else:
                await _broadcast_moved(card, prev, pause_col)
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

            pending_answer = human_answer  # injetado apenas na primeira etapa da retomada
            col = resume_stage or _first_stage(transitions, card.column_id, columns)
            if resume_stage and not _pipeline_handles(resume_stage, columns):
                # etapa gravada na pausa nao existe neste workflow (config mudou / workflow custom):
                # segue do inicio ativo em vez de terminar SUCCESS sem rodar nada.
                await log.event(
                    f"retomada: etapa '{resume_stage}' nao existe neste workflow — seguindo do inicio ativo"
                )
                col = next_active_column(transitions, card.column_id, pause_cols)

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

            # 2) laco de estagios — dispatch pelo agentKey das colunas do config (N4)
            while col and _pipeline_handles(col, columns):
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

                agent_key = _agent_key_for(col, columns)
                # config invalido e erro humano: agentKey sem agente mapeado nao avanca silencioso
                if agent_key not in _VALIDATE_CI_KEYS and not has_stage(agent_key):
                    await finish_pause(
                        f"coluna {col} com agentKey desconhecido: {agent_key}",
                        "Config do workflow referencia um agente que o backend nao mapeia (STAGE_AGENTS).",
                    )
                    return

                # validate-ci: push -> PR draft -> espera CI -> ready_to_merge (git/gh, nao um agente)
                if agent_key in _VALIDATE_CI_KEYS:
                    await log.event(f"── estagio: {col} ──")
                    vres = await run_validate_ci(
                        worktree=worktree, branch=card.branch_name or "", base_branch=base_branch,
                        card=card, project=project, gm=gm, log=log, stage_fn=stage_fn,
                        max_iterations=max_iterations, stage_context=stage_context,
                        account_fn=account,
                        fix_model=stage_model_for_agent("implement", card),
                    )
                    if vres["status"] == "pause":
                        await finish_pause(vres["reason"], vres.get("context"), question=vres.get("question"))
                        return
                    if vres.get("pr_url"):
                        execution.result = vres["pr_url"]
                        await s.commit()
                    col = next_active_column(transitions, col, pause_cols)  # -> ready_to_merge (para)
                    continue
                await log.event(f"── estagio: {col} ──")

                extra: dict = {"context": stage_context}
                if agent_key == "review":
                    extra["diff"] = await gm.diff_against_base(worktree, base_branch)
                elif agent_key == "implement" and chain_parts:
                    extra["plan"] = "\n\n".join(chain_parts)
                elif agent_key not in ("implement", "review") and chain_parts:
                    extra["chain"] = "\n\n".join(chain_parts)
                if pending_answer:
                    extra["human_answer"] = pending_answer
                    pending_answer = None
                if decisions_block and agent_key not in ("implement", "review"):
                    extra["decisions"] = decisions_block
                prompt = build_stage_prompt(agent_key, card.title, card.description or "", worktree, extra)
                res = await stage_fn(agent_key, worktree, prompt, card_id=card_id, on_log=log,
                                     model=stage_model_for_agent(agent_key, card))
                await log.flush()
                await account(res, stage_model_for_agent(agent_key, card))
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

                if agent_key == "implement":
                    nh = detect_needs_human(res.text)
                    if nh:
                        await finish_pause(
                            "implement: needs_human", nh,
                            question=f"O agente precisa da sua decisao para continuar:\n\n{nh}",
                        )
                        return
                    await gm.commit_all(worktree, f"wip: {card.title[:60]}")
                    col = next_active_column(transitions, col, pause_cols)

                elif agent_key == "review":
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
                                             model=stage_model_for_agent("review", card))
                        await log.flush()
                        await account(res, stage_model_for_agent("review", card))
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
                        # a COLUNA do implement vem do config (workflows custom podem renomea-la);
                        # o agentKey literal "implement" segue sendo o agente que corrige.
                        impl_col = next((c["key"] for c in columns if c.get("agentKey") == "implement"),
                                        "implement")
                        prev = card.column_id
                        moved, err = await repo.move(card_id, impl_col)
                        await s.commit()
                        if err:
                            await finish_pause("fix-loop: transicao invalida", err)
                            return
                        card = moved
                        await _broadcast_moved(card, prev, impl_col)
                        await log.event(f"── fix-loop #{iteration}: implement ──")
                        fix_prompt = build_stage_prompt(
                            "implement", card.title, card.description or "", worktree,
                            {"findings": f, "context": stage_context},
                        )
                        fix_res = await stage_fn("implement", worktree, fix_prompt, card_id=card_id, on_log=log,
                                                 model=stage_model_for_agent("implement", card))
                        await log.flush()
                        await account(fix_res, stage_model_for_agent("implement", card))
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
                        # `col` segue sendo a coluna de review do config — re-revisa no topo do laco
                        continue
                    col = next_active_column(transitions, col, pause_cols)  # -> validate_ci

                else:
                    # Estagio generico (plan e colunas SDD/custom): pausa em pendencias ou
                    # needs_human; senao ACUMULA a saida na cadeia que chega ao implement.
                    pend = parse_pending_questions(res.text)
                    if pend:
                        # Gate de escalacao (N3): clarifier julga com score 0-3 + decisoes passadas
                        # antes de acionar o humano. Fail-closed: erro/lixo -> pausa com tudo.
                        await log.event(f"── gate de escalacao: {len(pend)} pendencia(s) ──")
                        gate_prompt = (
                            f"Voce e o revisor de escalacao. Um estagio de planejamento ({agent_key}) "
                            f"levantou as pendencias abaixo para a tarefa: {card.title}.\n\n"
                            f"Pendencias:\n{_format_questions(pend)}\n\n"
                            + (f"{decisions_block}\n\n" if decisions_block else "")
                            + "Aplique o Pause-or-Decide (score 0-3, +1 por fonte verificavel entre "
                            "arquivo de regras do projeto, docs/, codigo existente e skills): score >= 2 "
                            "DECIDE citando as fontes; score < 2 mantem a pergunta pendente. "
                            'Devolva SO o JSON {"decisions": [{"question","decision","score","sources"}], '
                            '"pendingQuestions": [{"question","context"}]} — sem prosa fora dele.'
                        )
                        gate = await stage_fn("clarify", worktree, gate_prompt, card_id=card_id,
                                              on_log=log, model=stage_model_for_agent("clarify", card))
                        await log.flush()
                        await account(gate, stage_model_for_agent("clarify", card))
                        if gate.interrupted:
                            await finish_pause("interrompido pelo usuario",
                                               "O usuario parou a execucao durante o gate de escalacao.",
                                               question="Você interrompeu o agente. O que devo ajustar?")
                            return
                        verdict = parse_clarifier_output(gate.text if gate.ok else "")
                        raw = verdict["decisions"]

                        def _score(d):
                            try:
                                return int(d.get("score") or 0)
                            except (TypeError, ValueError, AttributeError):
                                return 0

                        # Invariante do Pause-or-Decide imposta em CODIGO (nao so no prompt):
                        # score < 2 NAO decide — a "decisao" e rebaixada a pendencia pro humano.
                        decided = [d for d in raw if isinstance(d, dict) and _score(d) >= 2]
                        demoted = [{"question": str(d.get("question", d)) if isinstance(d, dict) else str(d)}
                                   for d in raw if d not in decided]
                        remaining = (verdict["pendingQuestions"] + demoted) if (gate.ok and (raw or verdict["pendingQuestions"])) else pend
                        if decided:
                            try:
                                drepo = DecisionRepository(s)
                                for d in decided:
                                    await drepo.add(
                                        project_id=project_id, card_id=card_id,
                                        question=str(d.get("question", ""))[:2000],
                                        decision=str(d.get("decision", ""))[:2000],
                                        source="clarifier", score=_score(d),
                                        sources=[str(x) for x in v] if isinstance(v := d.get("sources"), list) else None,
                                        stage=agent_key,
                                    )
                                await s.commit()
                            except Exception:  # noqa: BLE001 — memoria best-effort
                                try:
                                    await s.rollback()  # sessao envenenada nao pode quebrar o que segue
                                except Exception:  # noqa: BLE001
                                    pass
                            await log.event(f"── gate decidiu {len(decided)} pendencia(s) com fonte ──")
                        if remaining:
                            await finish_pause(f"{agent_key}: pendencias", res.text[:1500],
                                               question=_format_questions(remaining))
                            return
                        # tudo decidido: re-roda o estagio UMA vez com as decisoes (mesmo canal do human_answer)
                        decided_text = "\n".join(
                            f"- {d.get('question')}: {d.get('decision')} "
                            f"(fontes: {', '.join(str(x) for x in (d.get('sources') if isinstance(d.get('sources'), list) else []))})"
                            for d in decided
                        )
                        decisions_note = (
                            "Decisoes do revisor de escalacao (com fontes do projeto) — siga-as:\n" + decided_text
                        )
                        rerun_extra = dict(extra)
                        # concatena (nao sobrescreve) uma resposta humana da retomada, se houver
                        prior_answer = extra.get("human_answer")
                        rerun_extra["human_answer"] = (
                            f"{prior_answer}\n\n{decisions_note}" if prior_answer else decisions_note
                        )
                        rerun_prompt = build_stage_prompt(agent_key, card.title, card.description or "",
                                                          worktree, rerun_extra)
                        res = await stage_fn(agent_key, worktree, rerun_prompt, card_id=card_id,
                                             on_log=log, model=stage_model_for_agent(agent_key, card))
                        await log.flush()
                        await account(res, stage_model_for_agent(agent_key, card))
                        if res.interrupted:
                            await finish_pause("interrompido pelo usuario",
                                               "O usuario parou a execucao.",
                                               question="Você interrompeu o agente. O que devo ajustar?")
                            return
                        if not res.ok:
                            await finish_pause(f"erro no re-run do {agent_key}", res.error)
                            return
                        if not (res.text or "").strip():
                            await finish_pause(f"estagio {agent_key} terminou sem output no re-run",
                                               "O agente encerrou o turno sem produzir texto.")
                            return
                        pend2 = parse_pending_questions(res.text)
                        if pend2:
                            # re-run ainda com pendencias: pausa direto (gate nao roda em loop)
                            await finish_pause(f"{agent_key}: pendencias apos o gate", res.text[:1500],
                                               question=_format_questions(pend2))
                            return
                    nh = detect_needs_human(res.text)
                    if nh:
                        await finish_pause(f"{agent_key}: needs_human", nh,
                                           question=f"O agente precisa da sua decisao para continuar:\n\n{nh}")
                        return
                    chain_parts.append(f"## Saida do estagio {agent_key}\n{res.text}")
                    col = next_active_column(transitions, col, pause_cols)

            # 3) parada limpa na fronteira (ex.: ready_to_merge): avanca e encerra
            if col and not _pipeline_handles(col, columns) and card.column_id != col:
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
