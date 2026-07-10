"""Estagio validate_ci (Fase 3c): valida local -> push -> PR draft -> espera CI -> ready_to_merge.

Nao e um agente unico: e orquestracao git/gh com dispatches pontuais de agente (implementer p/
corrigir, ci-triage p/ julgar falha). NUNCA faz merge nem promove o PR a ready — para no ready_to_merge.
Devolve um dict que o pipeline interpreta: {"status":"ok","pr_url":...} ou {"status":"pause",...}.
"""

import asyncio
from typing import Optional

from . import pr_service
from .findings import detect_needs_human, parse_ci_verdict
from .stage_runner import build_stage_prompt

_POLL_SECONDS = 15
_MAX_POLLS = 40  # ~10 min de teto de espera de CI


async def _run_command(worktree: str, command: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_shell(
        command, cwd=worktree,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode == 0, (out.decode(errors="replace") + err.decode(errors="replace")).strip()


def _pause(reason: str, context: str, question: str) -> dict:
    return {"status": "pause", "reason": reason, "context": context, "question": question}


async def run_validate_ci(*, worktree: str, branch: str, base_branch: str, card, project,
                          gm, log, stage_fn, max_iterations: int,
                          stage_context: "dict | None" = None,
                          account_fn=None,
                          fix_model: "str | None" = None) -> dict:
    """`stage_context`: contexto do projeto (rules_file etc.) repassado ao build_stage_prompt.
    `account_fn(res)`: contabiliza custo/tokens de cada dispatch de agente no run.
    `fix_model`: alias de modelo p/ o implementer (resolvido pelo pipeline — evita import circular).
    """
    title = card.title[:70]

    async def implement_fix(instruction: str) -> Optional[dict]:
        """Despacha o implementer p/ corrigir + commita. Retorna dict de pausa se needs_human/erro."""
        prompt = build_stage_prompt("implement", card.title, instruction, worktree,
                                    {"context": stage_context or {}})
        res = await stage_fn("implement", worktree, prompt, card_id=card.id, on_log=log,
                             model=fix_model)
        await log.flush()
        # contabiliza ANTES dos checks: turno interrompido/erro tambem custou tokens
        if account_fn:
            await account_fn(res)
        if res.interrupted:
            return _pause("interrompido pelo usuario", "durante o validate_ci",
                          "Você interrompeu. O que devo ajustar?")
        if not res.ok:
            return _pause("erro ao corrigir no validate_ci", res.error or "", "Falha ao corrigir. O que fazer?")
        if not (res.text or "").strip():
            return _pause("fix de validacao terminou sem output",
                          "O agente encerrou o turno sem produzir texto — provavel recusa ou turno abortado.",
                          "O agente encerrou o turno sem produzir texto. Como devo proceder?")
        nh = detect_needs_human(res.text)
        if nh:
            return _pause("validate_ci: needs_human", nh, f"O agente precisa da sua decisao:\n\n{nh}")
        await gm.commit_all(worktree, f"fix(ci): {title}")
        return None

    # 1) Validacao local (se o projeto define validateCommand)
    cmd = getattr(project, "validate_command", None)
    if cmd:
        it = 0
        while True:
            await log.event(f"── validacao local: {cmd} ──")
            ok, out = await _run_command(worktree, cmd)
            if ok:
                break
            if it >= max_iterations:
                return _pause("validacao local nao passou", out[:1500],
                              "A validação local segue falhando. Como devo proceder?")
            it += 1
            paused = await implement_fix(f"A validacao local (`{cmd}`) falhou. Corrija:\n{out[:2000]}")
            if paused:
                return paused

    # 2) Push da branch
    await log.event("── push da branch ──")
    ok, out = await pr_service.push_branch(worktree, branch)
    if not ok:
        return _pause("falha no push", out[:1500], "O push falhou. Verifique o remote/credenciais.")

    # 3) PR draft (idempotente)
    await log.event("── abrindo PR (draft) ──")
    ok, url = await pr_service.create_or_get_pr(
        worktree, base_branch, title,
        f"PR gerado pelo Sismais AI Orquestrador para: {card.title}\n\n(draft — aguardando revisao humana).",
    )
    if not ok:
        return _pause("falha ao abrir PR", url[:1500], "Não consegui abrir o PR. Verifique o gh/remote.")
    await log.event(f"PR: {url}")

    # 4) Espera CI (bounded) + triagem/fix de falhas
    it = 0
    polls = 0
    while True:
        status = await pr_service.check_status(worktree)
        state = status["state"]
        if state in ("none", "pass"):
            await log.event(f"── CI: {'sem checks' if state == 'none' else 'verde'} ──")
            return {"status": "ok", "pr_url": url}
        if state == "pending":
            polls += 1
            if polls > _MAX_POLLS:
                return _pause("CI nao concluiu no tempo", "timeout aguardando checks",
                              "A CI está demorando. Quer esperar mais, seguir mesmo assim, ou investigar?")
            await asyncio.sleep(_POLL_SECONDS)
            continue
        # state == "fail"
        if it >= max_iterations:
            return _pause(f"CI vermelha nao convergiu ({it} tentativas)", ", ".join(status["failing"])[:800],
                          "A CI segue vermelha após as correções. Como devo proceder?")
        await log.event(f"── CI vermelha: {', '.join(status['failing'])[:200]} — triagem ──")
        ci_log = await pr_service.failing_check_logs(worktree)
        diff = await gm.diff_against_base(worktree, base_branch)
        tprompt = build_stage_prompt("ci-triage", card.title, "", worktree,
                                     {"ci_log": ci_log, "diff": diff, "context": stage_context or {}})
        tres = await stage_fn("ci-triage", worktree, tprompt, card_id=card.id, on_log=log)
        await log.flush()
        if account_fn:
            await account_fn(tres)
        verdict = parse_ci_verdict(tres.text)
        if verdict["verdict"] == "unrelated":
            await log.event(f"── CI: falha unrelated ({verdict['porque'][:120]}) — seguindo ──")
            return {"status": "ok", "pr_url": url}
        it += 1
        paused = await implement_fix(f"A CI falhou (related). Corrija:\n{ci_log[:2000]}")
        if paused:
            return paused
        ok, out = await pr_service.push_branch(worktree, branch)
        if not ok:
            return _pause("falha no push do fix de CI", out[:1500], "O push da correção falhou.")
        polls = 0  # reinicia a espera apos novo push
