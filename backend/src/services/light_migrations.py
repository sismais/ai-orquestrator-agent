"""Migracoes leves idempotentes (sem Alembic) para DBs ja criados.

Adiciona colunas novas via ALTER TABLE quando faltarem. Seguro rodar sempre:
consulta o PRAGMA e so aplica o que falta. YAGNI ate precisarmos de Alembic.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# (tabela, coluna, definicao SQL) a garantir
_COLUMNS = [
    ("cards", "project_id", "VARCHAR(36)"),
]


async def run_light_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, column, ddl in _COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {r[1] for r in rows}  # r[1] = nome da coluna
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
