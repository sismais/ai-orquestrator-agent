"""Parsers do output textual dos agentes de estagio (reviewer/planner/implementer).

Os agentes reportam em texto livre com um bloco JSON no meio (as vezes cercado por ```json).
Estas funcoes extraem o que o orquestrador precisa de forma tolerante a prosa/cercas.

O review tem DOIS formatos de saida suportados:

- **candidatos** (`{"findings": [...]}`), o atual: lista plana em que cada achado carrega
  `conf`, `atribuicao` e `classe`. O balde e decidido depois, por `bucket_findings` — regra
  deterministica em codigo. Se o balde saisse do julgamento do modelo, o mesmo achado mudaria
  de balde entre iteracoes e o fix-loop nao convergiria.
- **baldes** (`{"blocks": [...], ...}`), o legado: aceito para `reviewCommand` plugavel e para
  nao exigir big-bang no sync com o devkit-core.

Paridade com o lado dos plugins: `plugins/sismais-dev-loop/scripts/findings.mjs` no repo
sismais-ai-plugins-private. As duas implementacoes precisam concordar na semantica — se
divergirem, o mesmo diff recebe veredito diferente no terminal e no Kanban, e ai ninguem
confia em nenhum dos dois.
"""

import json
import re
import unicodedata
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


def parse_review_findings_strict(text: str) -> Optional[dict]:
    """Extrai {blocks, fixNow, suggestions} do output do reviewer, tolerando prosa e
    cercas ```json ao redor. Devolve None quando o texto NAO contem nenhum JSON com
    os baldes. Falha-fechada: review nao-parseavel NAO pode aprovar o diff
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


def parse_review_findings(text: str) -> dict:
    """Extrai {blocks, fixNow, suggestions} do output do reviewer.

    Tolera prosa e cercas ```json ao redor. Se nao houver JSON com esses baldes,
    devolve os tres arrays vazios (fail-open — o pipeline usa a variante strict)."""
    return parse_review_findings_strict(text) or dict(_EMPTY_FINDINGS)


# ---------------------------------------------------------------------------
# Achados candidatos -> baldes (regra deterministica)
# ---------------------------------------------------------------------------

# `regressao` fica de fora de proposito: e vaga o bastante para virar balde de
# "mudou algo e eu nao gostei". Regressao que importa ja e `bug` ou
# `breaking-contrato`; a que nao altera comportamento observavel nao bloqueia nada.
DEFAULT_BLOCKING_CLASSES = [
    "bug", "seguranca", "rls", "multi-tenant", "perda-dados",
    "silent-failure", "breaking-contrato", "comment-errado", "pipeline",
]
DEFAULT_MIN_CONF = 80


def _fold(value: Any) -> str:
    """Sem acento e em caixa baixa — o modelo escreve 'pre-existente' ou 'pré-existente'
    conforme o dia, e isso nao pode mudar o balde."""
    s = "" if value is None else str(value)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def normalize_attribution(value: Any) -> str:
    """Ausencia e valor desconhecido caem em PR-ativado: erra para 'revisa', nunca para
    'ignora' (so `pre-existente` e descartavel, e por isso exige ser explicito)."""
    v = _fold(value)
    if v.startswith("pre-existente") or v.startswith("preexistente"):
        return "pre-existente"
    if v.startswith("pr-introduzido") or v.startswith("introduzido"):
        return "PR-introduzido"
    return "PR-ativado"


def _conf_of(f: dict) -> int:
    """Confianca ausente assume o corte: ausencia de dado nunca silencia achado."""
    c = f.get("conf")
    return int(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else DEFAULT_MIN_CONF


def _class_of(f: dict) -> str:
    """Classe ausente assume `bug` — pelo mesmo principio, erra para bloquear."""
    return _fold(f.get("classe")) or "bug"


def parse_review_candidates(text: str) -> Optional[list]:
    """Extrai `findings` (lista plana de candidatos). None quando o texto nao contem
    nenhum JSON com a chave — falha-fechada, igual aos baldes."""
    if not text:
        return None
    obj = _last_matching(text, lambda o: "findings" in o)
    if obj is None:
        return None
    return [f for f in _as_list(obj.get("findings")) if isinstance(f, dict)]


def parse_review_verdicts(text: str) -> Optional[list]:
    """Extrai `verdicts` do juiz (None se ausente)."""
    if not text:
        return None
    obj = _last_matching(text, lambda o: "verdicts" in o)
    if obj is None:
        return None
    return [v for v in _as_list(obj.get("verdicts")) if isinstance(v, dict)]


def parse_review_closures(text: str) -> Optional[list]:
    """Extrai `closures` do verificador de fechamento (None se ausente)."""
    if not text:
        return None
    obj = _last_matching(text, lambda o: "closures" in o)
    if obj is None:
        return None
    return [c for c in _as_list(obj.get("closures")) if isinstance(c, dict)]


def parse_review_coverage(text: str) -> Optional[str]:
    """Declaracao de cobertura da varredura sistematica. Vive FORA de findings: e fato
    sobre o que o revisor investigou, nao hipotese sobre o codigo — dentro da lista, o juiz
    a julgaria e o corte por confianca a descartaria, sumindo com o 'faltam estes Y'."""
    if not text:
        return None
    cobertura = None
    for obj in _iter_json_objects(text):
        if "findings" in obj and isinstance(obj.get("cobertura"), str) and obj["cobertura"].strip():
            cobertura = obj["cobertura"].strip()
    return cobertura


def apply_verdicts(candidates: list, verdicts: Optional[list]) -> dict:
    """O juiz decide a confianca final E a classe — os dois eixos vem da lente que achou,
    e e ela que tem vies de justificar (validade) e de inflar (impacto) o proprio achado.
    Deixar a classe sem revisao e pior que deixar a confianca: e a classe que decide o
    bloqueio, entao achado verdadeiro-mas-leve entraria em `blocks` e o fix-loop iteraria
    tentando 'corrigir' o que nao precisava.

    Achado sem veredito mantem o que tinha (degradar erra para 'reporta demais')."""
    if not verdicts:
        return {"findings": candidates, "semVeredito": len(candidates), "reclassificados": 0}
    by_id = {str(v["id"]): v for v in verdicts if v.get("id") is not None}
    out = []
    sem_veredito = 0
    reclassificados = 0
    for f in candidates:
        v = by_id.get(str(f.get("id"))) if f.get("id") is not None else None
        if v is None:
            sem_veredito += 1
            out.append(f)
            continue
        if v.get("refutado") is True:
            out.append({**f, "conf": 0, "motivoJuiz": v.get("motivo")})
            continue
        conf = v.get("conf")
        conf = int(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else _conf_of(f)
        novo = {**f, "conf": conf, "motivoJuiz": v.get("motivo")}
        classe = v.get("classe")
        if isinstance(classe, str) and classe.strip() and _fold(classe) != _class_of(f):
            novo["classeOriginal"] = _class_of(f)
            novo["classe"] = classe.strip()
            reclassificados += 1
        out.append(novo)
    return {"findings": out, "semVeredito": sem_veredito, "reclassificados": reclassificados}


def _dedupe_key(f: dict) -> str:
    """Duplicata = mesma LINHA + mesma classe. Sem numero de linha, o titulo entra na
    chave: dois bugs distintos no mesmo arquivo sao achados diferentes, e fundi-los
    apagaria um deles."""
    arquivo = _fold(f.get("arquivo"))
    tem_linha = re.search(r":\d+$", arquivo) is not None
    if tem_linha:
        return f"{arquivo}|{_class_of(f)}"
    return f"{arquivo}|{_class_of(f)}|{_fold(f.get('titulo'))}"


def _dedupe(findings: list) -> tuple:
    """Consolida na de maior confianca e preserva a autoria das duas — guardrail
    anti-vies: o consolidador so funde duplicata, nunca apaga achado por discordar."""
    by_key: dict = {}
    duplicatas = 0
    for f in findings:
        key = _dedupe_key(f)
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = {**f, "agentes": [f["agente"]] if f.get("agente") else []}
            continue
        duplicatas += 1
        winner = dict(f) if _conf_of(f) > _conf_of(prev) else dict(prev)
        agentes = list(prev.get("agentes") or [])
        if f.get("agente") and f["agente"] not in agentes:
            agentes.append(f["agente"])
        winner["agentes"] = agentes
        by_key[key] = winner
    return list(by_key.values()), duplicatas


def bucket_findings(
    candidates: list,
    blocking: Optional[list] = None,
    min_conf: int = DEFAULT_MIN_CONF,
    muted: Optional[list] = None,
) -> dict:
    """Regra de bucket, nesta ordem (a primeira que casar decide):

    1. classe silenciada pelo projeto -> descartada (ex.: `teste-ausente` em MVP)
    2. conf < min_conf                -> descartado
    3. atribuicao `pre-existente`     -> suggestions (nunca bloqueia merge)
    4. classe `nit`/`remover`         -> suggestions
    5. classe bloqueante              -> blocks
    6. resto                          -> fixNow

    Confianca mede certeza de que o achado e valido; classe mede o dano. So a classe
    decide bloqueio — conf alta em `nit` nao bloqueia, e custo do fix nunca entra.
    """
    blocking_set = {_fold(c) for c in (blocking if blocking is not None else DEFAULT_BLOCKING_CLASSES)}
    muted_set = {_fold(c) for c in (muted or [])}
    findings, duplicatas = _dedupe(candidates)
    out: dict = {"blocks": [], "fixNow": [], "suggestions": []}
    descartados = 0
    silenciados = 0
    for f in findings:
        conf = _conf_of(f)
        classe = _class_of(f)
        atribuicao = normalize_attribution(f.get("atribuicao"))
        item = {
            "titulo": f.get("titulo", "(sem titulo)"),
            "arquivo": f.get("arquivo"),
            "porque": f.get("porque", ""),
            "fonte": f.get("fonte"),
            "conf": conf,
            "classe": classe,
            "atribuicao": atribuicao,
        }
        if f.get("sugestao"):
            item["sugestao"] = f["sugestao"]
        if f.get("agentes"):
            item["agentes"] = f["agentes"]
        if classe in muted_set:
            silenciados += 1
            continue
        if conf < min_conf:
            descartados += 1
            continue
        if atribuicao == "pre-existente" or classe in ("nit", "remover"):
            out["suggestions"].append(item)
        elif classe in blocking_set:
            out["blocks"].append(item)
        else:
            out["fixNow"].append(item)
    for bucket in ("blocks", "fixNow", "suggestions"):
        out[bucket].sort(key=lambda x: x["conf"], reverse=True)
    meta = {
        "candidatos": len(candidates),
        "descartados": descartados,
        "duplicatas": duplicatas,
        "minConf": min_conf,
        "blocking": sorted(blocking_set),
    }
    if muted_set:
        # sai no meta para o relatorio poder DECLARAR o que ficou de fora: silencio sem
        # aviso faz o humano ler review limpo e concluir que aquilo passou pelo crivo.
        meta["silenciados"] = silenciados
        meta["muted"] = sorted(muted_set)
    out["meta"] = meta
    return out


def parse_review_result(
    text: str,
    blocking: Optional[list] = None,
    min_conf: int = DEFAULT_MIN_CONF,
    muted: Optional[list] = None,
) -> Optional[dict]:
    """Ponto unico de entrada do estagio de review, tolerante aos dois formatos.

    Candidatos (`findings`) passam pela regra deterministica; baldes vem do formato legado
    (reviewCommand plugavel) e sao usados como estao. None quando nenhum dos dois aparece —
    falha-fechada: review nao-parseavel NUNCA aprova o diff."""
    candidates = parse_review_candidates(text)
    if candidates is not None:
        return bucket_findings(candidates, blocking=blocking, min_conf=min_conf, muted=muted)
    return parse_review_findings_strict(text)


def parse_pending_questions(text: str) -> list:
    """Extrai a lista `pendingQuestions` de um JSON no texto ([] se ausente)."""
    if not text:
        return []
    obj = _last_matching(text, lambda o: "pendingQuestions" in o)
    if obj is None:
        return []
    return _as_list(obj.get("pendingQuestions"))


def parse_clarifier_output(text: str) -> dict:
    """Extrai {decisions, pendingQuestions} do clarifier (gate de escalacao, N3).

    Fail-closed: sem JSON parseavel -> nada decidido ({} vazios) e o chamador pausa
    com as perguntas originais."""
    empty = {"decisions": [], "pendingQuestions": []}
    if not text:
        return dict(empty)
    obj = _last_matching(text, lambda o: "decisions" in o or "pendingQuestions" in o)
    if obj is None:
        return dict(empty)
    return {
        "decisions": _as_list(obj.get("decisions")),
        "pendingQuestions": _as_list(obj.get("pendingQuestions")),
    }


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


def parse_track_verdict(text: str) -> dict:
    """Extrai {trilha, porque} do router de triagem. Default conservador: 'padrao'
    se nao parsear ou valor desconhecido (na duvida, trilha completa — criterio do router)."""
    if text:
        obj = _last_matching(text, lambda o: "trilha" in o)
        if obj is not None:
            t = str(obj.get("trilha", "")).lower()
            return {
                "trilha": "leve" if t == "leve" else "padrao",
                "porque": obj.get("porque") or obj.get("why") or "",
            }
    return {"trilha": "padrao", "porque": ""}


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
