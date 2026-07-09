"""Rotas de navegacao do sistema de arquivos local (para o seletor de pasta
do projeto). Servidor roda na mesma maquina do usuario — sem auth extra."""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/fs", tags=["filesystem"])


def _list_roots() -> list[dict]:
    if os.name == "nt":
        import string
        return [
            {"name": f"{letter}:\\", "path": f"{letter}:\\"}
            for letter in string.ascii_uppercase
            if os.path.exists(f"{letter}:\\")
        ]
    return [{"name": "/", "path": "/"}]


@router.get("/browse")
async def browse(path: Optional[str] = Query(None)):
    if not path:
        return {"path": None, "parent": None, "directories": _list_roots()}

    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="Caminho não encontrado ou não é uma pasta")

    try:
        entries = sorted(
            (e for e in p.iterdir() if e.is_dir() and not e.name.startswith(".")),
            key=lambda e: e.name.lower(),
        )
    except PermissionError:
        entries = []

    parent = str(p.parent) if p.parent != p else None
    return {
        "path": str(p),
        "parent": parent,
        "directories": [{"name": e.name, "path": str(e)} for e in entries],
    }
