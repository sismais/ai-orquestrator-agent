"""Helpers de push/PR/CI via `git` e `gh` (Fase 3c). Subprocess puro, cwd = worktree do card.

Nunca faz merge nem promove o PR a ready. `gh` precisa estar autenticado no host do backend e o
repo do projeto precisa ter remote no GitHub. Acoes reais so no repo-alvo de teste.
"""

import asyncio
import json
from typing import Optional


async def _run(args: list[str], cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def push_branch(worktree: str, branch: str) -> tuple[bool, str]:
    """`git push -u origin <branch>` a partir da worktree."""
    rc, out, err = await _run(["git", "push", "-u", "origin", branch], cwd=worktree)
    return rc == 0, (out + err).strip()


async def get_pr_url(worktree: str) -> Optional[str]:
    """URL do PR da branch atual (None se nao houver)."""
    rc, out, _ = await _run(["gh", "pr", "view", "--json", "url", "-q", ".url"], cwd=worktree)
    url = out.strip()
    return url if rc == 0 and url.startswith("http") else None


async def get_pr_state(worktree: str) -> str:
    """Estado do PR da branch atual: 'OPEN' | 'MERGED' | 'CLOSED' | 'UNKNOWN'.

    Detecta o merge feito pelo humano no GitHub — o orquestrador NUNCA faz merge."""
    rc, out, _ = await _run(["gh", "pr", "view", "--json", "state"], cwd=worktree)
    if rc != 0:
        return "UNKNOWN"
    try:
        state = (json.loads(out) or {}).get("state")
    except (json.JSONDecodeError, ValueError):
        return "UNKNOWN"
    return state if state in ("OPEN", "MERGED", "CLOSED") else "UNKNOWN"


async def create_or_get_pr(worktree: str, base: str, title: str, body: str) -> tuple[bool, str]:
    """Reusa o PR da branch se existir; senao cria um PR DRAFT. Retorna (ok, url_ou_erro)."""
    existing = await get_pr_url(worktree)
    if existing:
        return True, existing
    rc, out, err = await _run(
        ["gh", "pr", "create", "--draft", "--base", base, "--title", title, "--body", body],
        cwd=worktree,
    )
    text = (out + err).strip()
    if rc != 0:
        return False, text
    # gh imprime a URL do PR no stdout
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("http"):
            return True, line
    url = await get_pr_url(worktree)
    return (url is not None), (url or text)


async def check_status(worktree: str) -> dict:
    """Estado agregado da CI do PR da branch atual.

    Retorna {"state": "none"|"pending"|"pass"|"fail", "failing": [nomes]}.
    `none` = sem PR ou sem checks (tratado como verde pelo orquestrador).
    """
    rc, out, _ = await _run(
        ["gh", "pr", "view", "--json", "statusCheckRollup"], cwd=worktree
    )
    if rc != 0:
        return {"state": "none", "failing": []}
    try:
        rollup = (json.loads(out) or {}).get("statusCheckRollup") or []
    except (json.JSONDecodeError, ValueError):
        return {"state": "none", "failing": []}
    if not rollup:
        return {"state": "none", "failing": []}

    any_pending = False
    failing: list[str] = []
    for c in rollup:
        name = c.get("name") or c.get("context") or "check"
        if c.get("__typename") == "CheckRun" or "status" in c:
            if c.get("status") != "COMPLETED":
                any_pending = True
            elif c.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                failing.append(name)
        else:  # StatusContext
            state = c.get("state")
            if state in ("PENDING", "EXPECTED"):
                any_pending = True
            elif state != "SUCCESS":
                failing.append(name)

    if failing:
        return {"state": "fail", "failing": failing}
    if any_pending:
        return {"state": "pending", "failing": []}
    return {"state": "pass", "failing": []}


async def failing_check_logs(worktree: str) -> str:
    """Resumo/log das checks que falharam (best-effort, para a triagem)."""
    rc, out, err = await _run(["gh", "pr", "checks"], cwd=worktree)
    return (out + err).strip()[:4000]
