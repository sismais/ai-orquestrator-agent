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
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

from . import session_registry as sessions
from .runner_service import DEVKIT_CLAUDE
from ..config.model_ids import get_profile

DEVKIT_AGENTS = DEVKIT_CLAUDE / "agents"

# coluna (agentKey) -> (arquivo do agente, tools permitidas)
STAGE_AGENTS: dict[str, tuple[str, list[str]]] = {
    "plan": ("sismais-dev-planner", ["Read", "Glob", "Grep"]),
    "implement": ("sismais-dev-implementer", ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]),
    "review": ("sismais-dev-reviewer", ["Read", "Glob", "Grep", "Bash"]),
    "ci-triage": ("sismais-dev-ci-triage", ["Read", "Glob", "Grep", "Bash"]),
}


# Padrao oficial Anthropic (anti-parada-prematura): sem isto, um agente que encerra o
# turno com um plano/promessa passa como estagio concluido e o pipeline commita o nada.
AUTONOMY_SNIPPET = (
    "\n\n## Operacao autonoma\n"
    "Voce opera de forma autonoma dentro de um pipeline; o usuario nao acompanha em tempo real. "
    "Antes de encerrar o turno, verifique seu ultimo paragrafo: se for um plano, uma analise, uma "
    "pergunta retorica ou uma promessa de trabalho nao feito, execute esse trabalho AGORA com tool "
    "calls em vez de encerrar. Encerre somente com o resultado final no formato pedido — ou, "
    "quando a decisao for genuinamente humana, com o sinal de escalacao definido nas SUAS "
    "instrucoes acima (`status: needs_human` ou bloco `pendingQuestions`, conforme o seu estagio)."
)


def build_stage_options(stage_key: str, worktree: str, model: "str | None") -> ClaudeAgentOptions:
    """Ponto unico de montagem das options do estagio (perfis por modelo — N1)."""
    body, tools = load_stage_agent(stage_key)
    profile = get_profile(model) if model else None
    append = body + AUTONOMY_SNIPPET + (profile.prompt_append if profile else "")
    options_kwargs = dict(
        cwd=worktree,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": append},
        allowed_tools=tools,
        permission_mode="acceptEdits",
    )
    if model:
        options_kwargs["model"] = profile.model_id
    return ClaudeAgentOptions(**options_kwargs)


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
    ctx = extra.get("context") or {}
    rules_file = ctx.get("rules_file") or "AGENTS.md"
    ctx_lines = [f"Voce trabalha no repositorio em `{worktree}` (worktree isolada do card)."]
    if ctx.get("project_name"):
        ctx_lines.append(f"Projeto: {ctx['project_name']}.")
    if ctx.get("objective"):
        ctx_lines.append(f"Objetivo do projeto: {ctx['objective']}")
    if ctx.get("requested_by"):
        ctx_lines.append(
            f"Solicitante do card: {ctx['requested_by']} — calibre profundidade e comunicacao para esse perfil."
        )
    ctx_lines.append(f"Regras do projeto: siga o `{rules_file}` se existir na worktree.")
    header = "\n".join(ctx_lines)
    answer = extra.get("human_answer")
    answer_block = (
        f"\n\nO humano respondeu a uma pausa anterior — considere isto acima de tudo:\n\"{answer}\"\n"
        if answer else ""
    )

    if stage_key == "plan":
        # Planner e read-only (Read/Glob/Grep): devolve o plano como TEXTO (nao escreve arquivo no repo).
        # O orquestrador captura o texto e passa pro implement — nada de artefato do runner na branch.
        return (
            f"{header}\n\nTarefa: {task}{answer_block}\n\n"
            "Produza o conteudo do plano de implementacao (abordagem, arquivos afetados, reuso, riscos), "
            "derivando do que ja existe no projeto. Responda com o plano em markdown. "
            "Se uma decisao de arquitetura nao tiver base no projeto, devolva tambem um bloco JSON "
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
        plan = extra.get("plan")
        plan_block = f"\n\nPlano de referencia (do estagio anterior):\n{plan}\n" if plan else ""
        return (
            f"{header}\n\nTarefa: {task}{answer_block}{plan_block}\n\n"
            "Implemente editando o codigo e criando/atualizando testes quando fizer sentido. "
            "NAO faca commit. "
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

    if stage_key == "ci-triage":
        ci_log = extra.get("ci_log") or "(sem log)"
        diff = extra.get("diff") or "(diff vazio)"
        return (
            f"{header}\n\nUma check de CI falhou. Julgue se a falha e causada pelo diff. "
            'Devolva SO o JSON `{ "verdict": "related" | "unrelated", "porque": "..." }`.\n\n'
            f"Log da CI:\n```\n{ci_log}\n```\n\nDiff do PR:\n```diff\n{diff}\n```"
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
    interrupted: bool = False
    usage: Optional[dict] = None
    used_model: Optional[str] = None


# Status HTTP que valem 1 retry no mesmo modelo (rate limit / erro de servidor).
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504, 529}


def _classify_result(result_msg, last_assistant_stop_reason: "str | None") -> str:
    """Classifica o fim do turno: 'ok' | 'refusal' | 'transient' | 'error'.

    Campos do claude-agent-sdk 0.2.110: ResultMessage.stop_reason/is_error/subtype/
    api_error_status; AssistantMessage.stop_reason (a recusa pode aparecer em qualquer um).
    Turno sem ResultMessage = stream truncado -> 'error'.
    """
    if getattr(result_msg, "stop_reason", None) == "refusal" or last_assistant_stop_reason == "refusal":
        return "refusal"
    if result_msg is None:
        return "error"
    if getattr(result_msg, "is_error", False):
        status = getattr(result_msg, "api_error_status", None)
        if status in _TRANSIENT_HTTP:
            return "transient"
        return "error"
    return "ok"


@dataclass
class _AttemptOutcome:
    classification: str            # ok | refusal | transient | error
    text: str = ""
    cost_usd: Optional[float] = None
    usage: Optional[dict] = None
    interrupted: bool = False
    error: Optional[str] = None


async def _run_single_attempt(stage_key: str, worktree: str, prompt: str,
                              card_id: "str | None", on_log, model_alias: "str | None") -> _AttemptOutcome:
    """UMA sessao SDK: conecta, roda o turno, classifica o fim. Sem politica de retry aqui."""
    options = build_stage_options(stage_key, worktree, model_alias)
    texts: list[str] = []
    cost = None
    usage = None
    result_msg = None
    last_stop = None
    client = ClaudeSDKClient(options)
    try:
        await client.connect()
        if card_id:
            sessions.register(card_id, client)
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                last_stop = getattr(message, "stop_reason", None) or last_stop
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
                        if on_log:
                            r = on_log(block.text)
                            if inspect.isawaitable(r):
                                await r
            elif isinstance(message, ResultMessage):
                result_msg = message
                cost = getattr(message, "total_cost_usd", None)
                usage = getattr(message, "usage", None) or None
    except Exception as e:  # noqa: BLE001
        interrupted = bool(card_id and sessions.was_interrupted(card_id))
        return _AttemptOutcome(
            classification="ok" if interrupted else "error",
            text="\n".join(texts), cost_usd=cost, usage=usage,
            interrupted=interrupted, error=None if interrupted else str(e),
        )
    finally:
        if card_id:
            sessions.unregister(card_id)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    interrupted = bool(card_id and sessions.was_interrupted(card_id))
    if card_id:
        sessions.clear_interrupt(card_id)
    classification = _classify_result(result_msg, last_stop)
    error = None
    if classification != "ok" and result_msg is not None:
        detail = getattr(result_msg, "errors", None) or getattr(result_msg, "result", None)
        error = f"{getattr(result_msg, 'subtype', '?')} | {detail}" if detail else getattr(result_msg, "subtype", "erro")
    return _AttemptOutcome(
        classification=classification, text="\n".join(texts), cost_usd=cost,
        usage=usage, interrupted=interrupted, error=error,
    )


async def run_stage(stage_key: str, worktree: str, prompt: str, card_id: Optional[str] = None,
                    on_log=None, model: Optional[str] = None) -> StageResult:
    """Roda um estagio com resiliencia (N1): recusa -> 1 retry no modelo de fallback do
    perfil; erro transiente (HTTP 429/5xx) -> 1 retry no mesmo modelo; interrupcao nunca
    re-tenta. Custo/usage somados entre tentativas; `used_model` = alias que produziu o
    resultado final. Assinatura estavel (contrato stage_fn do pipeline/validate_ci).
    """
    total_cost = 0.0
    total_usage: dict = {}

    def _merge(outcome: _AttemptOutcome) -> None:
        nonlocal total_cost
        if outcome.cost_usd:
            total_cost += float(outcome.cost_usd)
        if isinstance(outcome.usage, dict):
            for k, v in outcome.usage.items():
                if isinstance(v, (int, float)):
                    total_usage[k] = total_usage.get(k, 0) + v

    async def _note(msg: str) -> None:
        if on_log:
            r = on_log(msg)
            if inspect.isawaitable(r):
                await r

    alias = model
    transient_retried = False
    fallback_used = False
    for _ in range(3):  # teto duro: 1 tentativa + 1 retry transiente + 1 fallback
        outcome = await _run_single_attempt(stage_key, worktree, prompt, card_id, on_log, alias)
        _merge(outcome)
        if outcome.interrupted:
            return StageResult(ok=True, text=outcome.text, cost_usd=total_cost or None,
                               interrupted=True, usage=total_usage or None, used_model=alias)
        if outcome.classification == "ok":
            return StageResult(ok=True, text=outcome.text, cost_usd=total_cost or None,
                               usage=total_usage or None, used_model=alias)
        if outcome.classification == "transient" and not transient_retried:
            transient_retried = True
            await _note(f"\n[orquestrador] erro transiente da API ({outcome.error}) — re-tentando...\n")
            continue
        if outcome.classification == "refusal" and not fallback_used:
            fallback = get_profile(alias).fallback_alias if alias else None
            if fallback:
                fallback_used = True
                await _note(f"\n[orquestrador] recusa do modelo `{alias}` — re-tentando com `{fallback}` (perfil de fallback)\n")
                alias = fallback
                continue
            return StageResult(ok=False, text=outcome.text, cost_usd=total_cost or None,
                               error=f"recusa do modelo `{alias}` (sem fallback no perfil)",
                               usage=total_usage or None, used_model=alias)
        # refusal com fallback ja usado, transient repetido, ou error definitivo
        err = outcome.error or outcome.classification
        if outcome.classification == "refusal":
            err = f"recusa persistente (modelos: {model} -> {alias})"
        return StageResult(ok=False, text=outcome.text, cost_usd=total_cost or None,
                           error=err, usage=total_usage or None, used_model=alias)
    return StageResult(ok=False, error="teto de tentativas do estagio excedido",
                       cost_usd=total_cost or None, usage=total_usage or None, used_model=alias)
