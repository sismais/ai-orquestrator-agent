"""Executa UM estagio do DevKit como uma query focada do SDK.

O backend e o orquestrador (substitui a skill sismais-dev-loop, cujos scripts de estado
nao foram migrados). Para cada coluna-com-estagio, carregamos o agente do DevKit
correspondente (`devkit/.claude/agents/sismais-dev-<stage>.md`), usamos o corpo do .md como
role apendado ao system prompt do Claude Code, e restringimos as tools as declaradas por ele.
"""

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

from .runner_service import DEVKIT_CLAUDE

DEVKIT_AGENTS = DEVKIT_CLAUDE / "agents"

# coluna (agentKey) -> (arquivo do agente, tools permitidas)
STAGE_AGENTS: dict[str, tuple[str, list[str]]] = {
    "plan": ("sismais-dev-planner", ["Read", "Glob", "Grep"]),
    "implement": ("sismais-dev-implementer", ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]),
    "review": ("sismais-dev-reviewer", ["Read", "Glob", "Grep", "Bash"]),
}


def has_stage(stage_key: str) -> bool:
    return stage_key in STAGE_AGENTS


def _strip_frontmatter(md: str) -> str:
    """Remove o bloco YAML de frontmatter (--- ... ---) do inicio do .md, se houver."""
    text = md.lstrip("﻿")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            after = text.find("\n", end + 1)
            return text[after + 1:].lstrip() if after != -1 else ""
    return text


def load_stage_agent(stage_key: str) -> tuple[str, list[str]]:
    """Devolve (corpo do agente sem frontmatter, tools permitidas) para o estagio."""
    if stage_key not in STAGE_AGENTS:
        raise ValueError(f"Estagio sem agente mapeado: {stage_key}")
    filename, tools = STAGE_AGENTS[stage_key]
    path = DEVKIT_AGENTS / f"{filename}.md"
    body = _strip_frontmatter(path.read_text(encoding="utf-8"))
    return body, tools


def build_stage_prompt(stage_key: str, title: str, description: str,
                       worktree: str, extra: Optional[dict] = None) -> str:
    """Monta o prompt do usuario para o estagio (o role vem do system prompt)."""
    extra = extra or {}
    task = f"{title}. {description}".strip().rstrip(".")
    header = f"Voce trabalha no repositorio em `{worktree}` (worktree isolada do card)."

    if stage_key == "plan":
        return (
            f"{header}\n\nTarefa: {task}\n\n"
            "Produza o conteudo do plano de implementacao e ESCREVA-O em `.sismais/plan.md` "
            "(crie o diretorio se preciso). Derive do que ja existe no projeto. "
            "Se uma decisao de arquitetura nao tiver base no projeto, devolva um bloco JSON "
            '`{ "pendingQuestions": [ { "question": "...", "context": "..." } ] }` ao final.'
        )

    if stage_key == "implement":
        findings = extra.get("findings")
        if findings:
            items = _format_findings(findings)
            return (
                f"{header}\n\nCorrija EXATAMENTE os achados de review a seguir "
                f"(nada alem — YAGNI). Edite codigo e testes. NAO faca commit.\n\n{items}"
            )
        return (
            f"{header}\n\nTarefa: {task}\n\n"
            "Implemente editando o codigo e criando/atualizando testes quando fizer sentido. "
            "Siga o AGENTS.md do projeto se existir. NAO faca commit. "
            "Ao terminar, reporte os arquivos mudados e `status: done` (ou `needs_human` com o motivo)."
        )

    if stage_key == "review":
        diff = extra.get("diff") or "(diff vazio)"
        return (
            f"{header}\n\nRevise o diff a seguir contra as regras/padroes do projeto. "
            "Leia o codigo real, nao confie em relatos. Devolva SO o JSON de achados "
            "(`blocks`/`fixNow`/`suggestions`), sem prosa fora dele.\n\n"
            f"```diff\n{diff}\n```"
        )

    # fallback generico
    return f"{header}\n\nTarefa: {task}"


def _format_findings(findings: dict) -> str:
    lines = []
    for bucket in ("blocks", "fixNow"):
        for f in findings.get(bucket, []):
            titulo = f.get("titulo") or f.get("title") or "(sem titulo)"
            arquivo = f.get("arquivo") or f.get("file") or ""
            porque = f.get("porque") or f.get("why") or ""
            loc = f" [{arquivo}]" if arquivo else ""
            lines.append(f"- ({bucket}) {titulo}{loc}: {porque}")
    return "\n".join(lines) if lines else "(sem achados)"


@dataclass
class StageResult:
    ok: bool
    text: str = ""
    cost_usd: Optional[float] = None
    error: Optional[str] = None


async def run_stage(stage_key: str, worktree: str, prompt: str, on_log=None) -> StageResult:
    """Roda um estagio: query focada com o role do agente e as tools dele. on_log(str) opcional."""
    body, tools = load_stage_agent(stage_key)
    options = ClaudeAgentOptions(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": body},
        allowed_tools=tools,
        permission_mode="acceptEdits",
    )

    texts: list[str] = []
    cost = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
                        if on_log:
                            r = on_log(block.text)
                            if inspect.isawaitable(r):
                                await r
            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
    except Exception as e:  # noqa: BLE001
        return StageResult(ok=False, text="\n".join(texts), cost_usd=cost, error=str(e))

    return StageResult(ok=True, text="\n".join(texts), cost_usd=cost)
