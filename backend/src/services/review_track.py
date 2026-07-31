"""Ciclo de vida dos achados ENTRE iteracoes do fix-loop.

Cada iteracao despacha revisores frescos — de proposito: sessao de review que persiste
cristaliza o proprio engano (um falso positivo da rodada 1 entra no contexto como fato e e
reafirmado na rodada 2) e passa a verificar "meu conselho foi seguido?" em vez de "o
problema sumiu?".

O que nao pode ser fresco e a MEMORIA do que foi apontado. Ela vive aqui, como dado: ids
estaveis atravessam as iteracoes e o revisor da rodada N recebe os achados abertos como
entrada, nao como lembranca.

Invariante central: **ausencia nao fecha achado.** Um achado que simplesmente nao reaparece
no relatorio continua aberto (`semVerificacao`) — some do radar por amostragem diferente,
nao por ter sido corrigido. Fechar exige veredito explicito, verificado contra o codigo.
Mesma falha-fechada do parse: o silencio nunca aprova.

Paridade com `plugins/sismais-dev-loop/scripts/review-track.mjs` (sismais-ai-plugins-private).
"""

import hashlib
import unicodedata
from typing import Any, Optional


def _fold(value: Any) -> str:
    s = "" if value is None else str(value)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def stable_id(finding: dict) -> str:
    """A linha NAO entra na identidade: o proprio fix desloca as linhas, e casar por
    `arquivo:linha` faria o mesmo achado virar outro a cada iteracao — nada fecharia."""
    import re
    arquivo = re.sub(r":\d+$", "", _fold(finding.get("arquivo")))
    chave = f"{arquivo}|{_fold(finding.get('classe'))}|{_fold(finding.get('titulo'))}"
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:8]


def actionable_of(bucketed: dict) -> list:
    """So o acionavel entra no ciclo de vida. `suggestions` nao bloqueia nem obriga
    correcao — rastrea-las inflaria o estado sem mudar decisao nenhuma."""
    return list(bucketed.get("blocks") or []) + list(bucketed.get("fixNow") or [])


def track_findings(
    current: dict,
    previous: Optional[dict] = None,
    closures: Optional[list] = None,
    iteration: int = 1,
) -> dict:
    anteriores: dict = {f["fid"]: dict(f) for f in ((previous or {}).get("findings") or [])}
    fechamentos = {str(c["fid"]): c for c in (closures or []) if c and c.get("fid")}
    meta = {"novos": 0, "resolvidos": 0, "reabertos": 0, "semVerificacao": 0, "aindaAbertos": 0}

    vistos_agora = set()
    for f in actionable_of(current):
        fid = f.get("fid") or stable_id(f)
        vistos_agora.add(fid)
        antigo = anteriores.get(fid)
        if antigo is None:
            anteriores[fid] = {
                "fid": fid, "titulo": f.get("titulo"), "arquivo": f.get("arquivo"),
                "classe": f.get("classe"), "conf": f.get("conf"),
                "status": "aberto", "abertoNa": iteration, "tentativas": 0, "reaberturas": 0,
            }
            meta["novos"] += 1
            continue
        # Reabertura: ja tinha sido dado como resolvido e voltou. E o sinal de ciclo
        # implementer<->reviewer, e o motivo mais comum de estourar max_iterations.
        if antigo.get("status") == "resolvido":
            antigo["reaberturas"] = antigo.get("reaberturas", 0) + 1
            meta["reabertos"] += 1
        antigo["status"] = "aberto"
        antigo["classe"] = f.get("classe")
        antigo["conf"] = f.get("conf")
        antigo["tentativas"] = antigo.get("tentativas", 0) + 1
        anteriores[fid] = antigo

    for fid, f in anteriores.items():
        if f.get("status") == "resolvido" and fid not in vistos_agora:
            continue
        c = fechamentos.get(fid)
        if c is not None and c.get("resolvido") is True:
            f["status"] = "resolvido"
            f["resolvidoNa"] = iteration
            f["motivoFechamento"] = c.get("motivo")
            meta["resolvidos"] += 1
            continue
        if fid not in vistos_agora:
            # nao reapareceu e ninguem verificou: continua aberto, e isso fica visivel
            f["status"] = "aberto"
            f["semVerificacao"] = True
            meta["semVerificacao"] += 1
        else:
            f.pop("semVerificacao", None)
            if c is not None and c.get("resolvido") is False:
                f["motivoNaoResolvido"] = c.get("motivo")

    findings = list(anteriores.values())
    meta["aindaAbertos"] = sum(1 for f in findings if f.get("status") == "aberto")
    # So para quando nao sobrou nada acionavel aberto. "O revisor nao achou nada nesta
    # rodada" nao e a mesma coisa — pode ter passado longe do que apontou antes.
    meta["podeParar"] = meta["aindaAbertos"] == 0
    # Reabertura nao e progresso: e o loop andando em circulo. Escale ao humano em vez
    # de gastar as iteracoes restantes.
    meta["escalar"] = meta["reabertos"] > 0
    return {"findings": findings, "meta": meta}
