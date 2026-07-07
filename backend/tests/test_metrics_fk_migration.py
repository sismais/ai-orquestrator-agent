import src.models  # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.services.light_migrations import migrate_metrics_fk_target


async def test_migrate_metrics_fk_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE active_project (id VARCHAR PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text(
            "CREATE TABLE project_metrics (id VARCHAR PRIMARY KEY, project_id VARCHAR "
            "REFERENCES active_project(id))"
        ))
        await conn.execute(text(
            "CREATE TABLE execution_metrics (id VARCHAR PRIMARY KEY, project_id VARCHAR "
            "REFERENCES active_project(id))"
        ))
    await migrate_metrics_fk_target(engine)
    await migrate_metrics_fk_target(engine)
    async with engine.begin() as conn:
        for table in ("project_metrics", "execution_metrics"):
            fks = (await conn.execute(text(f"PRAGMA foreign_key_list({table})"))).fetchall()
            targets = {row[2] for row in fks}  # row[2] = tabela referenciada
            assert "active_project" not in targets
            assert "projects" in targets
    await engine.dispose()
