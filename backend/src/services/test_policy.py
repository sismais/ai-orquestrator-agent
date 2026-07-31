"""Politica de cobranca de testes no review, por projeto.

Em projeto MVP, exigir teste e ruido garantido; em projeto grande e em producao, nao
exigir e risco. `test_policy` assume `none` | `critical-only` | `full`.

Resolucao, primeira que responder decide:

1. Declaracao explicita no projeto (coluna `test_policy`).
2. Sinal OBJETIVO do repositorio: o `validate_command` executa testes? existem arquivos
   `*.test.*` / `*.spec.*` / `test_*.py`?
3. `none`.

O sinal objetivo vem antes de interpretar prosa do rulesFile de proposito: prosa nao
separa os casos reais. Nem o AGENTS.md do GMS Web nem o do central-video exigem teste
por escrito — mas o GMS tem 167 arquivos de teste e `npm test` no gate, e o outro tem
zero e nenhum script de teste.

Paridade com a skill `sismais-dev-review` (sismais-ai-plugins-private).
"""

import os
import re
from pathlib import Path
from typing import Optional

VALID_POLICIES = ("none", "critical-only", "full")

# Comandos que denotam execucao de testes dentro do validate_command.
_TEST_CMD = re.compile(
    r"\b(npm|pnpm|yarn|bun)\s+(run\s+)?test\b|\bnpx?\s+(jest|vitest|mocha)\b"
    r"|\bpytest\b|\bpython\s+-m\s+pytest\b|\bgo\s+test\b|\bcargo\s+test\b"
    r"|\bdotnet\s+test\b|\bmvn\s+test\b|\bvitest\b|\bjest\b",
    re.IGNORECASE,
)

_TEST_FILE = re.compile(r"(\.test\.|\.spec\.|^test_.*\.py$|_test\.(py|go|ts|js)$)")
_SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "dist", "build", "__pycache__",
              ".next", ".venv", "target", "vendor", ".pytest_cache", "coverage"}
_WALK_DIR_BUDGET = 2000


def _has_test_files(root: str) -> bool:
    """True se o repo tem ao menos um arquivo de teste.

    Usa os.walk com PODA de diretorio, nao glob recursivo: `Path.glob('**/*.test.*')`
    desce em node_modules (o filtro so viria depois) e num projeto Node sem testes isso
    varreria a arvore inteira — a cada execucao de pipeline. Tem teto de diretorios pelo
    mesmo motivo: a resposta e booleana, entao vale sair cedo e errar para `none`.
    """
    base = Path(root)
    if not base.is_dir():
        return False
    visitados = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if _TEST_FILE.search(name):
                return True
        visitados += 1
        if visitados > _WALK_DIR_BUDGET:
            return False
    return False


def resolve_test_policy(declared: Optional[str], validate_command: Optional[str],
                        project_path: Optional[str]) -> tuple[str, str]:
    """Devolve (politica, motivo). O motivo entra no log — politica silenciosa faz o
    humano ler review limpo sem saber que a cobertura nem foi olhada."""
    if declared and declared.strip().lower() in VALID_POLICIES:
        return declared.strip().lower(), "declarado no projeto"
    if validate_command and _TEST_CMD.search(validate_command):
        return "full", "validateCommand executa testes"
    if project_path and _has_test_files(project_path):
        return "full", "o repositorio tem arquivos de teste"
    return "none", "projeto sem testes e sem gate de teste"


def muted_classes_for(policy: str) -> list[str]:
    """Classes que o bucket deve descartar sob a politica.

    Vive no bucket, e nao so nos prompts, porque instrucao um dia escapa: desligar a
    lente de testes sem silenciar a classe faz o review geral absorver o trabalho e o
    projeto continuar recebendo cobranca de teste, so que de outro agente."""
    return ["teste-ausente"] if policy == "none" else []


def prompt_note_for(policy: str) -> str:
    """Instrucao a anexar no prompt das lentes que NAO sao a de testes."""
    if policy == "none":
        return ("\n\nPolitica de testes deste projeto: `none` — NAO reporte achado de "
                "classe `teste-ausente` nem comente falta de cobertura.")
    if policy == "critical-only":
        return ("\n\nPolitica de testes deste projeto: `critical-only` — so cobre teste "
                "onde o dano e irreversivel (dinheiro, dados do cliente, controle de acesso).")
    return ""
