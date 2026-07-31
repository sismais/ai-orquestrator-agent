"""Resolucao da politica de testes por projeto.

Paridade com a skill `sismais-dev-review` (sismais-ai-plugins-private): declaracao ->
sinal objetivo -> none.
"""

from src.services.findings import bucket_findings
from src.services.test_policy import (
    muted_classes_for,
    prompt_note_for,
    resolve_test_policy,
)


class TestResolucao:
    def test_declaracao_explicita_manda(self, tmp_path):
        # mesmo com sinal objetivo apontando para full, a declaracao vence
        pol, why = resolve_test_policy("none", "npm test", str(tmp_path))
        assert pol == "none" and "declarado" in why

    def test_declaracao_invalida_cai_no_sinal_objetivo(self, tmp_path):
        pol, _ = resolve_test_policy("mais ou menos", "npm test", str(tmp_path))
        assert pol == "full"

    def test_validate_command_que_roda_testes_implica_full(self, tmp_path):
        for cmd in ("npm run lint && npm test", "pytest -q", "./venv/bin/python -m pytest",
                    "go test ./...", "npx vitest run", "cargo test"):
            pol, why = resolve_test_policy(None, cmd, str(tmp_path))
            assert pol == "full", cmd
            assert "validateCommand" in why

    def test_arquivos_de_teste_no_repo_implicam_full(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.test.ts").write_text("x", encoding="utf-8")
        pol, why = resolve_test_policy(None, "npm run build", str(tmp_path))
        assert pol == "full" and "arquivos de teste" in why

    def test_projeto_sem_teste_e_sem_gate_cai_em_none(self, tmp_path):
        # o caso do central-video: sem .test.*, sem script de teste
        (tmp_path / "index.html").write_text("<html>", encoding="utf-8")
        pol, why = resolve_test_policy(None, "npm run build", str(tmp_path))
        assert pol == "none" and "sem testes" in why

    def test_nao_confunde_node_modules_com_teste_do_projeto(self, tmp_path):
        nm = tmp_path / "node_modules" / "lib"
        nm.mkdir(parents=True)
        (nm / "index.test.js").write_text("x", encoding="utf-8")
        pol, _ = resolve_test_policy(None, "npm run build", str(tmp_path))
        assert pol == "none", "teste de dependencia nao e teste do projeto"

    def test_caminho_inexistente_nao_explode(self):
        pol, _ = resolve_test_policy(None, None, "/nao/existe")
        assert pol == "none"


class TestEfeitos:
    def test_none_silencia_a_classe_no_bucket(self):
        # o muted vive no CODIGO porque instrucao um dia escapa: desligar so a lente
        # faria o review geral absorver o trabalho
        achados = [{"titulo": "sem teste", "porque": "p", "classe": "teste-ausente",
                    "conf": 100, "atribuicao": "PR-introduzido", "arquivo": "a.ts"},
                   {"titulo": "bug", "porque": "p", "classe": "bug",
                    "conf": 90, "atribuicao": "PR-introduzido", "arquivo": "b.ts"}]
        r = bucket_findings(achados, muted=muted_classes_for("none"))
        assert r["fixNow"] == []
        assert [f["arquivo"] for f in r["blocks"]] == ["b.ts"]
        assert r["meta"]["silenciados"] == 1

    def test_full_e_critical_only_nao_silenciam(self):
        assert muted_classes_for("full") == []
        assert muted_classes_for("critical-only") == []

    def test_nota_do_prompt_por_politica(self):
        assert "NAO reporte" in prompt_note_for("none")
        assert "irreversivel" in prompt_note_for("critical-only")
        assert prompt_note_for("full") == ""
