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
    # v2: Document conversion & ingestion (MarkItDown)
    (2, "add documents table", [
        """CREATE TABLE IF NOT EXISTS documents (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            filename VARCHAR(256) NOT NULL,
            original_path VARCHAR(512) NOT NULL,
            markdown_content TEXT NOT NULL,
            file_type VARCHAR(32) NOT NULL,
            file_size INTEGER NOT NULL,
            created_at VARCHAR(32) NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents(user_id)",
    ]),
]

# Future migrations would be appended here:
# (3, "add X column", ["ALTER TABLE ... ADD COLUMN ..."]),


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
