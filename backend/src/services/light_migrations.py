"""Migracoes leves idempotentes (sem Alembic) para DBs ja criados.

Adiciona colunas novas via ALTER TABLE quando faltarem. Seguro rodar sempre:
consulta o PRAGMA e so aplica o que falta. YAGNI ate precisarmos de Alembic.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# (tabela, coluna, definicao SQL) a garantir
_COLUMNS = [
    ("cards", "project_id", "VARCHAR(36)"),
    ("executions", "fix_iterations", "INTEGER"),
    ("cards", "requested_by", "VARCHAR(120)"),
    ("projects", "objective", "TEXT"),
]


async def run_light_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, column, ddl in _COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {r[1] for r in rows}  # r[1] = nome da coluna
            if not existing:
                continue  # tabela nao existe ainda — o create_all a cria ja com a coluna
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


# Remapeamento de colunas legadas -> colunas do workflow dev novo
_COLUMN_REMAP = {"test": "review", "completed": "done", "archived": "done", "cancelado": "paused"}


async def remap_legacy_columns(engine: AsyncEngine) -> None:
    """Remapeia cards em colunas legadas para as colunas do workflow atual (idempotente)."""
    async with engine.begin() as conn:
        for old, new in _COLUMN_REMAP.items():
            await conn.execute(
                text("UPDATE cards SET column_id = :new WHERE column_id = :old"),
                {"new": new, "old": old},
            )


# Remap de aliases de modelo legados -> aliases atuais (idempotente)
_MODEL_ALIAS_REMAP = {"opus-4.5": "opus-4.8", "sonnet-4.5": "sonnet-5"}
_MODEL_COLUMNS = ("model_plan", "model_implement", "model_test", "model_review")


async def remap_legacy_model_aliases(engine: AsyncEngine) -> None:
    """Remapeia aliases de modelo antigos nos cards para os atuais (idempotente)."""
    async with engine.begin() as conn:
        for col in _MODEL_COLUMNS:
            for old, new in _MODEL_ALIAS_REMAP.items():
                await conn.execute(
                    text(f"UPDATE cards SET {col} = :new WHERE {col} = :old"),
                    {"new": new, "old": old},
                )


async def migrate_metrics_fk_target(engine: AsyncEngine) -> None:
    """Repointa o FK de project_metrics/execution_metrics de active_project -> projects.

    SQLite nao faz ALTER de FK; como as tabelas de metrics estao vazias em DEV, o
    caminho seguro e dropar (se ainda apontam pra active_project e estao vazias) e
    deixar o create_all recriar com o FK novo. Idempotente.
    """
    from ..database import Base
    async with engine.begin() as conn:
        for table in ("project_metrics", "execution_metrics"):
            exists = (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
            ), {"t": table})).first()
            if not exists:
                continue
            fks = (await conn.execute(text(f"PRAGMA foreign_key_list({table})"))).fetchall()
            targets = {row[2] for row in fks}
            if "active_project" not in targets:
                continue  # ja migrado
            count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
            if count and count > 0:
                print(f"[light_migrations] {table} tem {count} linhas; FK nao repontado automaticamente")
                continue
            await conn.execute(text(f"DROP TABLE {table}"))
        await conn.run_sync(Base.metadata.create_all)
