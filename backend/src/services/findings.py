"""Parsers do output textual dos agentes de estagio (reviewer/planner/implementer).

Os agentes reportam em texto livre com um bloco JSON no meio (as vezes cercado por ```json).
Estas funcoes extraem o que o orquestrador precisa de forma tolerante a prosa/cercas.
"""

import json
import re
from typing import Any, Optional

_EMPTY_FINDINGS = {"blocks": [], "fixNow": [], "suggestions": []}


def _iter_json_objects(text: str):
    """Gera dicts JSON validos encontrados no texto, por varredura de chaves balanceadas."""
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            yield obj
                    except (json.JSONDecodeError, ValueError):
                        pass
                    start = -1


def _last_matching(text: str, predicate) -> Optional[dict]:
    """Ultimo objeto JSON do texto que satisfaz o predicado (None se nenhum)."""
    found = None
    for obj in _iter_json_objects(text):
        if predicate(obj):
            found = obj
    return found


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def parse_review_findings(text: str) -> dict:
    """Extrai {blocks, fixNow, suggestions} do output do reviewer.

    Tolera prosa e cercas ```json ao redor. Se nao houver JSON com esses baldes,
    devolve os tres arrays vazios (nao bloqueia por ausencia de parse).
    """
    if not text:
        return dict(_EMPTY_FINDINGS)
    obj = _last_matching(
        text,
        lambda o: any(k in o for k in ("blocks", "fixNow", "suggestions")),
    )
    if obj is None:
        return dict(_EMPTY_FINDINGS)
    return {
        "blocks": _as_list(obj.get("blocks")),
        "fixNow": _as_list(obj.get("fixNow")),
        "suggestions": _as_list(obj.get("suggestions")),
    }


def parse_review_findings_strict(text: str) -> Optional[dict]:
    """Como parse_review_findings, mas devolve None quando o texto NAO contem nenhum
    JSON com os baldes. Falha-fechada: review nao-parseavel NAO pode aprovar o diff
    (o parser tolerante devolvia baldes vazios e liberava o caminho do merge)."""
    if not text:
        return None
    obj = _last_matching(
        text,
        lambda o: any(k in o for k in ("blocks", "fixNow", "suggestions")),
    )
    if obj is None:
        return None
    return {
        "blocks": _as_list(obj.get("blocks")),
        "fixNow": _as_list(obj.get("fixNow")),
        "suggestions": _as_list(obj.get("suggestions")),
    }


def parse_pending_questions(text: str) -> list:
    """Extrai a lista `pendingQuestions` de um JSON no texto ([] se ausente)."""
    if not text:
        return []
    obj = _last_matching(text, lambda o: "pendingQuestions" in o)
    if obj is None:
        return []
    return _as_list(obj.get("pendingQuestions"))


def parse_ci_verdict(text: str) -> dict:
    """Extrai {verdict, porque} do ci-triage. Default conservador: 'related' se nao parsear
    (assim o orquestrador tenta corrigir em vez de ignorar uma falha real)."""
    if text:
        obj = _last_matching(text, lambda o: "verdict" in o)
        if obj is not None:
            v = str(obj.get("verdict", "")).lower()
            return {
                "verdict": "unrelated" if v == "unrelated" else "related",
                "porque": obj.get("porque") or obj.get("why") or "",
            }
    return {"verdict": "related", "porque": ""}


_NEEDS_HUMAN_RE = re.compile(
    r'(?:"?status"?\s*[:=]\s*"?needs_human"?|needs[_\s-]?human)',
    re.IGNORECASE,
)


def detect_needs_human(text: str) -> Optional[str]:
    """Se o output sinaliza needs_human, devolve um trecho de contexto; senao None."""
    if not text:
        return None
    m = _NEEDS_HUMAN_RE.search(text)
    if not m:
        return None
    # Contexto: a linha do match (util para o motivo da pausa).
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end = text.find("\n", m.end())
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip() or "needs_human"
