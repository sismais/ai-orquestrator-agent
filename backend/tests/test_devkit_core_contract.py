"""Contrato com o devkit-core (fonte única em sismais-ai-plugins-private).

Duas garantias:
1. Anti-drift: os arquivos sincronizados em devkit/ batem com o manifest gerado pelo
   sync (`devkit-core/sync.mjs`). Editar a cópia local sem passar pelo core = teste vermelho.
2. Paridade de parser: `parse_review_findings_strict` produz exatamente o esperado pelas
   fixtures compartilhadas (as mesmas que o `findings.mjs` dos plugins testa).
"""

import hashlib
import json
from pathlib import Path

import pytest

from src.services.findings import parse_review_findings_strict

DEVKIT = Path(__file__).resolve().parents[2] / "devkit"
MANIFEST = DEVKIT / "devkit-core.manifest.json"
FIXTURES = DEVKIT / "schemas" / "fixtures" / "review-findings"


def test_manifest_existe():
    assert MANIFEST.is_file(), (
        "devkit/devkit-core.manifest.json ausente — rode o sync do devkit-core "
        "(node devkit-core/sync.mjs --platform <este repo>) no sismais-ai-plugins-private"
    )


def test_arquivos_sincronizados_batem_com_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    divergentes = []
    for rel, expected_sha in manifest["files"].items():
        path = DEVKIT / rel
        if not path.is_file():
            divergentes.append(f"{rel} (ausente)")
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != expected_sha:
            divergentes.append(rel)
    assert not divergentes, (
        "Drift do devkit-core detectado (nao edite as copias locais; edite o core e "
        f"re-sincronize): {divergentes}"
    )


def _fixture_cases():
    if not FIXTURES.is_dir():
        return []
    return sorted(FIXTURES.glob("*.input.txt"))


@pytest.mark.parametrize("input_path", _fixture_cases(), ids=lambda p: p.name)
def test_parser_paridade_com_fixtures_compartilhadas(input_path):
    expected_path = input_path.with_name(input_path.name.replace(".input.txt", ".expected.json"))
    text = input_path.read_text(encoding="utf-8")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert parse_review_findings_strict(text) == expected, f"fixture {input_path.name}"


def test_fixtures_presentes():
    assert len(_fixture_cases()) >= 5, "fixtures do devkit-core nao sincronizadas em devkit/schemas/"
