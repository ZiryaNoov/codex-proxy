"""Version-based database migration runner."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .models import _schema_version

logger = logging.getLogger("codex-proxy.db")

# Each migration is a tuple of (version, description, list_of_sql_statements).
# Migrations run sequentially. The _schema_version table tracks the current version.
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    # v1: Initial schema — tables are created by metadata.create_all()
    # This entry ensures the version table has a row.
    (1, "initial schema", []),
]

# Future migrations would be appended here:
# (2, "add X column", ["ALTER TABLE ... ADD COLUMN ..."]),
# (3, "create Y index", ["CREATE INDEX ..."])


async def run_migrations(conn: AsyncConnection) -> None:
    """Run all pending database migrations.

    Checks _schema_version and applies any migrations not yet applied.
    """
    # Ensure the schema_version table exists
    await conn.run_sync(lambda sync_conn: _schema_version.create(sync_conn, checkfirst=True))

    # Get current version
    result = await conn.execute(text("SELECT COALESCE(MAX(version), 0) FROM _schema_version"))
    row = result.fetchone()
    current_version = row[0] if row else 0

    # Apply pending migrations
    for version, description, sqls in MIGRATIONS:
        if version <= current_version:
            continue
        logger.info("Running migration v%d: %s", version, description)
        for sql in sqls:
            await conn.execute(text(sql))
        await conn.execute(
            _schema_version.insert().values(version=version)
        )
        await conn.commit()
        logger.info("Migration v%d applied successfully", version)
