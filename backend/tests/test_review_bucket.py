"""Regra deterministica de bucket e ciclo de vida dos achados.

Espelha `plugins/sismais-dev-loop/scripts/findings.test.mjs` e `review-track.test.mjs` do
repo sismais-ai-plugins-private: os dois modos (terminal e painel) precisam concordar na
semantica, senao o mesmo diff recebe veredito diferente em cada um.
"""

from src.services.findings import (
    DEFAULT_BLOCKING_CLASSES,
    apply_verdicts,
    bucket_findings,
    normalize_attribution,
    parse_attribution,
    parse_review_candidates,
    parse_review_closures,
    parse_review_coverage,
    parse_review_result,
    parse_review_verdicts,
)
from src.services.review_track import stable_id, track_findings


def cand(**over):
    base = {"titulo": "t", "porque": "p", "conf": 90,
            "atribuicao": "PR-introduzido", "classe": "bug"}
    base.update(over)
    return base


def bucket(blocks=None, fix_now=None):
    return {"blocks": blocks or [], "fixNow": fix_now or [], "suggestions": []}


class TestNormalizacao:
    def test_acento_e_sufixo_nao_mudam_o_balde(self):
        assert normalize_attribution("pré-existente") == "pre-existente"
        assert normalize_attribution("pre-existente-nao-relacionado") == "pre-existente"
        assert normalize_attribution("PR-INTRODUZIDO") == "PR-introduzido"

    def test_ausencia_e_desconhecido_erram_para_revisar(self):
        assert normalize_attribution(None) == "PR-ativado"
        assert normalize_attribution("sei la") == "PR-ativado"


class TestBucket:
    def test_classe_decide_o_balde_confianca_nao(self):
        r = bucket_findings([
            cand(classe="bug", arquivo="a.ts"),
            cand(classe="teste-ausente", arquivo="b.ts"),
            cand(classe="nit", arquivo="c.ts", conf=100),
        ])
        assert [f["arquivo"] for f in r["blocks"]] == ["a.ts"]
        assert [f["arquivo"] for f in r["fixNow"]] == ["b.ts"]
        # conf 100 num nit continua sendo sugestao — impacto e a classe
        assert [f["arquivo"] for f in r["suggestions"]] == ["c.ts"]

    def test_pre_existente_nunca_bloqueia(self):
        r = bucket_findings([cand(arquivo="x.ts", classe="seguranca",
                                  atribuicao="pré-existente", conf=99)])
        assert r["blocks"] == [] and len(r["suggestions"]) == 1

    def test_corte_por_confianca(self):
        r = bucket_findings([cand(arquivo="a.ts", conf=79), cand(arquivo="b.ts", conf=80)])
        assert [f["arquivo"] for f in r["blocks"]] == ["b.ts"]
        assert r["meta"]["descartados"] == 1

    def test_campo_ausente_nunca_silencia_achado(self):
        r = bucket_findings([{"titulo": "t", "porque": "p", "arquivo": "a.ts"}])
        assert len(r["blocks"]) == 1
        assert r["blocks"][0]["conf"] == 80
        assert r["blocks"][0]["classe"] == "bug"
        assert r["blocks"][0]["atribuicao"] == "PR-ativado"

    def test_ordena_por_confianca_desc(self):
        r = bucket_findings(
            [cand(arquivo="a.ts", classe="perf", conf=85), cand(arquivo="b.ts", classe="perf", conf=95)],
            blocking=["perf"],
        )
        assert [f["conf"] for f in r["blocks"]] == [95, 85]

    def test_duplicata_funde_por_linha_e_classe(self):
        r = bucket_findings([
            cand(arquivo="a.ts:42", conf=85, agente="reviewer", titulo="null aqui"),
            cand(arquivo="a.ts:42", conf=95, agente="errors", titulo="possivel null"),
        ])
        assert len(r["blocks"]) == 1
        assert r["blocks"][0]["conf"] == 95
        assert sorted(r["blocks"][0]["agentes"]) == ["errors", "reviewer"]

    def test_sem_linha_titulos_distintos_sao_achados_distintos(self):
        # fundir aqui apagaria um bug real — o consolidador nunca deleta achado
        r = bucket_findings([
            cand(arquivo="a.ts", titulo="race no save"),
            cand(arquivo="a.ts", titulo="null no delete"),
        ])
        assert len(r["blocks"]) == 2
        assert r["meta"]["duplicatas"] == 0

    def test_classe_silenciada_some_mesmo_com_confianca_maxima(self):
        r = bucket_findings(
            [cand(arquivo="a.ts", classe="teste-ausente", conf=100), cand(arquivo="b.ts", classe="bug")],
            muted=["teste-ausente"],
        )
        assert r["fixNow"] == []
        assert [f["arquivo"] for f in r["blocks"]] == ["b.ts"]
        # o relatorio precisa poder DECLARAR o que foi silenciado
        assert r["meta"]["silenciados"] == 1
        assert r["meta"]["muted"] == ["teste-ausente"]

    def test_regressao_fora_dos_bloqueantes_comment_errado_dentro(self):
        assert "regressao" not in DEFAULT_BLOCKING_CLASSES
        assert "comment-errado" in DEFAULT_BLOCKING_CLASSES

    def test_irmaos_do_mesmo_grupo_nao_se_fundem(self):
        # e o gemeo esquecido: corrigir um e perder o outro reabre achado na rodada seguinte
        grupo = "front espelha o 1o ramo de tenant_over_limit_state"
        r = bucket_findings([cand(id="r1", arquivo="src/a.ts:10", grupo=grupo),
                             cand(id="r2", arquivo="src/a.ts:110", grupo=grupo)])
        assert len(r["blocks"]) == 2 and r["meta"]["duplicatas"] == 0
        assert r["blocks"][0]["grupo"] == grupo

    def test_verificacao_sobrevive_ate_o_balde(self):
        r = bucket_findings([cand(arquivo="a.ts:1", verificacao="grep -c X docs/ retorna 0")])
        assert r["blocks"][0]["verificacao"] == "grep -c X docs/ retorna 0"

    def test_descartado_por_confianca_e_preservado_com_o_motivo_do_juiz(self):
        r = apply_verdicts([cand(id="r1", arquivo="a.ts:1", conf=90)],
                           [{"id": "r1", "conf": 70, "motivo": "cenario depende de status que nao vi"}])
        out = bucket_findings(r["findings"])
        assert out["blocks"] == [] and out["meta"]["descartados"] == 1
        assert len(out["abaixoDoCorte"]) == 1
        assert out["abaixoDoCorte"][0]["conf"] == 70
        assert "nao vi" in out["abaixoDoCorte"][0]["motivoJuiz"]

    def test_silenciado_pelo_projeto_nao_e_preservado(self):
        # foi desligado, nao cortado: reoferecer na proxima rodada seria reabrir a cobranca
        r = bucket_findings([cand(arquivo="a.ts", classe="teste-ausente", conf=40)],
                            muted=["teste-ausente"])
        assert "abaixoDoCorte" not in r and r["meta"]["silenciados"] == 1


class TestJuiz:
    def test_substitui_conf_refutado_zera_sem_veredito_preserva(self):
        candidates = [cand(id="r1", conf=90, arquivo="a.ts:1"),
                      cand(id="e1", conf=90, arquivo="b.ts:2"),
                      cand(id="t1", conf=88, arquivo="c.ts:3")]
        r = apply_verdicts(candidates, [
            {"id": "r1", "conf": 95, "motivo": "confirmado"},
            {"id": "e1", "refutado": True, "motivo": "o catch relanca"},
        ])
        assert r["findings"][0]["conf"] == 95
        assert r["findings"][1]["conf"] == 0
        assert r["findings"][2]["conf"] == 88
        assert r["semVeredito"] == 1
        assert [f["conf"] for f in bucket_findings(r["findings"])["blocks"]] == [95, 88]

    def test_reclassifica_e_tira_do_bloqueio_o_que_nao_altera_comportamento(self):
        # o caso real do PR 465 do GMS Web: remocao de stubs inalcancaveis como `regressao`
        r = apply_verdicts(
            [cand(id="r1", classe="regressao", arquivo="src/router.tsx:240", conf=85)],
            [{"id": "r1", "conf": 92, "classe": "doc",
              "motivo": "stubs sem referencia no repo — nao muda comportamento observavel"}],
        )
        assert r["reclassificados"] == 1
        assert r["findings"][0]["classeOriginal"] == "regressao"
        out = bucket_findings(r["findings"], blocking=["bug", "regressao"])
        assert out["blocks"] == []
        assert len(out["fixNow"]) == 1 and out["fixNow"][0]["conf"] == 92

    def test_classe_igual_nao_conta_como_reclassificacao(self):
        r = apply_verdicts([cand(id="r1", classe="bug")],
                           [{"id": "r1", "conf": 90, "classe": "BUG", "motivo": "ok"}])
        assert r["reclassificados"] == 0

    def test_reatribui_para_pre_existente_e_o_achado_deixa_de_bloquear(self):
        # o juiz percebia que o caminho se comporta igual antes do diff e so podia
        # escrever isso no motivo; o achado entrava em blocks como PR-ativado
        r = apply_verdicts(
            [cand(id="r1", atribuicao="PR-ativado", arquivo="a.ts:9", conf=88)],
            [{"id": "r1", "conf": 88, "atribuicao": "pre-existente",
              "motivo": "identico antes do diff; o diff so torna visivel"}],
        )
        assert r["reatribuidos"] == 1
        assert r["findings"][0]["atribuicaoOriginal"] == "PR-ativado"
        out = bucket_findings(r["findings"])
        assert out["blocks"] == [] and len(out["suggestions"]) == 1

    def test_atribuicao_fora_do_contrato_preserva_a_da_lente(self):
        # erro seguro: juiz escrevendo torto nao tira achado da decisao de merge
        assert parse_attribution("sei la") is None
        r = apply_verdicts([cand(id="r1", atribuicao="PR-introduzido")],
                           [{"id": "r1", "conf": 90, "atribuicao": "talvez pre?", "motivo": "m"}])
        assert r["reatribuidos"] == 0
        assert r["findings"][0]["atribuicao"] == "PR-introduzido"

    def test_duplicata_de_funde_o_que_a_chave_por_linha_nao_funde(self):
        # tres lentes ancoraram o mesmo defeito em linhas diferentes do mesmo arquivo
        r = apply_verdicts(
            [cand(id="r1", arquivo="src/planStates.ts:35", conf=85, agente="reviewer"),
             cand(id="e1", arquivo="src/planStates.ts:40", conf=92, agente="errors"),
             cand(id="c1", arquivo="src/planStates.ts:43", conf=80, agente="comments")],
            [{"id": "r1", "conf": 85, "motivo": "ok"},
             {"id": "e1", "conf": 92, "duplicataDe": "r1", "motivo": "mesmo defeito"},
             {"id": "c1", "conf": 80, "duplicataDe": "e1", "motivo": "idem (cadeia ate r1)"}],
        )
        out = bucket_findings(r["findings"])
        assert len(out["blocks"]) == 1 and out["blocks"][0]["conf"] == 92
        assert out["meta"]["duplicatas"] == 2
        assert sorted(out["blocks"][0]["locais"]) == [
            "src/planStates.ts:35", "src/planStates.ts:40", "src/planStates.ts:43"]

    def test_duplicata_de_com_alvo_invalido_nao_apaga_achado(self):
        sem_alvo = bucket_findings([cand(id="r1", arquivo="a.ts:1", duplicataDe="nao-existe")])
        assert len(sem_alvo["blocks"]) == 1
        ciclo = bucket_findings([cand(id="r1", arquivo="a.ts:1", duplicataDe="r2"),
                                 cand(id="r2", arquivo="b.ts:2", duplicataDe="r1")])
        assert len(ciclo["blocks"]) == 2


class TestParsers:
    def test_candidatos_ultimo_objeto_vence_prosa_tolerada(self):
        assert parse_review_candidates("so prosa") is None
        assert parse_review_candidates('{"blocks": []}') is None
        assert parse_review_candidates(
            '{"findings": [{"titulo":"a"}]}\nreescrevendo:\n{"findings": []}') == []

    def test_verdicts_e_closures(self):
        assert parse_review_verdicts('{"findings": []}') is None
        assert parse_review_verdicts('```json\n{"verdicts": [{"id":"r1","motivo":"m"}]}\n```') == [
            {"id": "r1", "motivo": "m"}]
        assert parse_review_closures('{"closures": [{"fid":"a1","resolvido":true,"motivo":"m"}]}') == [
            {"fid": "a1", "resolvido": True, "motivo": "m"}]

    def test_cobertura_vive_fora_de_findings(self):
        assert parse_review_coverage('{"findings": [], "cobertura": "N=42, faltam 27"}') == "N=42, faltam 27"
        assert parse_review_coverage('{"findings": []}') is None

    def test_parse_review_result_aceita_os_dois_contratos(self):
        novo = parse_review_result('{"findings": [{"titulo":"t","porque":"p","classe":"bug","conf":95}]}')
        assert len(novo["blocks"]) == 1
        legado = parse_review_result('{"fixNow": [{"titulo": "t", "porque": "p"}]}')
        assert legado == {"blocks": [], "fixNow": [{"titulo": "t", "porque": "p"}], "suggestions": []}

    def test_falha_fechada_sem_json_nenhum(self):
        # review nao-parseavel NUNCA aprova o diff
        assert parse_review_result("O diff parece otimo, aprovado!") is None


class TestCicloDeVida:
    def test_stable_id_ignora_numero_da_linha(self):
        f = {"titulo": "engole erro", "arquivo": "src/x.ts:42", "classe": "silent-failure"}
        assert stable_id(f) == stable_id({**f, "arquivo": "src/x.ts:97"})
        assert stable_id(f) != stable_id({**f, "arquivo": "src/y.ts:42"})

    def test_ausencia_nao_fecha_achado(self):
        f = cand(arquivo="src/x.ts:42", classe="bug")
        prev = track_findings(current=bucket([f]), iteration=1)
        # rodada 2 amostrou outros arquivos e nem tocou no assunto
        r = track_findings(current=bucket([]), previous=prev, iteration=2)
        assert r["meta"]["resolvidos"] == 0
        assert r["meta"]["semVerificacao"] == 1
        assert r["meta"]["podeParar"] is False, "silencio do revisor nao pode liberar o merge"

    def test_fechamento_explicito_resolve(self):
        prev = track_findings(current=bucket([cand(arquivo="src/x.ts:42")]), iteration=1)
        fid = prev["findings"][0]["fid"]
        r = track_findings(current=bucket([]), previous=prev, iteration=2,
                           closures=[{"fid": fid, "resolvido": True, "motivo": "relanca"}])
        assert r["meta"]["resolvidos"] == 1 and r["meta"]["podeParar"] is True

    def test_reabertura_escala_para_humano(self):
        f = cand(arquivo="src/x.ts:42")
        it1 = track_findings(current=bucket([f]), iteration=1)
        fid = it1["findings"][0]["fid"]
        it2 = track_findings(current=bucket([]), previous=it1, iteration=2,
                             closures=[{"fid": fid, "resolvido": True, "motivo": "ok"}])
        assert it2["meta"]["escalar"] is False
        it3 = track_findings(current=bucket([f]), previous=it2, iteration=3)
        assert it3["meta"]["reabertos"] == 1
        assert it3["meta"]["escalar"] is True, "reabertura para o loop, nao gasta o teto"

    def test_fecha_dois_abre_tres_nao_e_convergencia(self):
        a, b = cand(titulo="a", arquivo="x.ts:1"), cand(titulo="b", arquivo="x.ts:2")
        it1 = track_findings(current=bucket([a, b]), iteration=1)
        fids = [f["fid"] for f in it1["findings"]]
        it2 = track_findings(
            current=bucket([cand(titulo="c", arquivo="y.ts:1"), cand(titulo="d", arquivo="y.ts:2"),
                            cand(titulo="e", arquivo="y.ts:3")]),
            previous=it1, iteration=2,
            closures=[{"fid": fid, "resolvido": True, "motivo": "ok"} for fid in fids],
        )
        assert it2["meta"]["resolvidos"] == 2
        assert it2["meta"]["novos"] == 3
        assert it2["meta"]["podeParar"] is False

    def test_suggestions_ficam_fora_do_ciclo_de_vida(self):
        r = track_findings(current={"blocks": [], "fixNow": [], "suggestions": [cand(classe="nit")]},
                           iteration=1)
        assert r["meta"]["novos"] == 0 and r["meta"]["podeParar"] is True
