"""Database layer — async engine, session factory, and initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .engine import create_engine_from_config
from .migrations import run_migrations

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import logging
from pathlib import Path

from .models import metadata

logger = logging.getLogger("codex-proxy.db")

# Default database path
DEFAULT_DB_PATH = Path.home() / ".codex-proxy" / "proxy.db"
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"


async def init_db(db_url: str | None = None) -> tuple[AsyncEngine, async_sessionmaker]:
    """Initialize the database: create engine, run migrations, return session factory.

    Args:
        db_url: SQLAlchemy async URL. Defaults to SQLite at ~/.codex-proxy/proxy.db.

    Returns:
        Tuple of (AsyncEngine, async_sessionmaker).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    url = db_url or DEFAULT_DB_URL

    # Ensure parent directory exists for SQLite
    if url.startswith("sqlite"):
        path = url.split(":///", 1)[-1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine_from_config(url)
    async with engine.begin() as conn:
        # Create all tables (idempotent)
        await conn.run_sync(metadata.create_all)
        # Run version-based migrations
        await run_migrations(conn)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("Database initialized: %s", _mask_url(url))
    return engine, session_factory


async def close_db(engine: AsyncEngine) -> None:
    """Dispose of the database engine."""
    await engine.dispose()
    logger.info("Database connection closed")


def _mask_url(url: str) -> str:
    """Mask passwords in database URLs for logging."""
    if "@" in url:
        # postgresql+asyncpg://user:password@host/db
        parts = url.split("://", 1)
        if len(parts) == 2:
            rest = parts[1]
            if "@" in rest:
                creds, after = rest.split("@", 1)
                if ":" in creds:
                    user = creds.split(":")[0]
                    return f"{parts[0]}://{user}:***@{after}"
    return url
