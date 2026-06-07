"""Async engine factory for SQLAlchemy."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine_from_config(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        url: SQLAlchemy async connection URL.
             SQLite:  sqlite+aiosqlite:///path/to/proxy.db
             Postgres: postgresql+asyncpg://user:pass@host/db
        echo: If True, emit SQL statements for debugging.

    Returns:
        AsyncEngine instance.
    """
    connect_args: dict = {}

    if url.startswith("sqlite"):
        # SQLite-specific optimizations
        connect_args["check_same_thread"] = False

    engine = create_async_engine(
        url,
        echo=echo,
        connect_args=connect_args,
        # Connection pool settings
        pool_pre_ping=True,
        pool_recycle=3600,
    )

    # Set SQLite WAL mode for better concurrent writes
    if url.startswith("sqlite"):

        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine
