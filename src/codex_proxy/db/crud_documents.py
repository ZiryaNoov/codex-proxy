"""CRUD operations for the documents table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from .models import documents


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


async def create_document(
    session,
    *,
    filename: str,
    original_path: str,
    markdown_content: str,
    file_type: str,
    file_size: int,
    user_id: str | None = None,
) -> dict:
    """Insert a new document record. Returns the document as dict."""
    doc_id = _new_id()
    now = _now()
    await session.execute(
        documents.insert().values(
            id=doc_id,
            user_id=user_id,
            filename=filename,
            original_path=original_path,
            markdown_content=markdown_content,
            file_type=file_type,
            file_size=file_size,
            created_at=now,
        )
    )
    await session.commit()
    return await get_document(session, doc_id)


async def get_document(session, doc_id: str) -> dict | None:
    """Get a document by ID. Returns dict or None."""
    result = await session.execute(
        select(documents).where(documents.c.id == doc_id)
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_documents(
    session,
    *,
    user_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List documents, optionally filtered by user_id."""
    stmt = select(documents).order_by(documents.c.created_at.desc())
    if user_id is not None:
        stmt = stmt.where(documents.c.user_id == user_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def delete_document(session, doc_id: str) -> bool:
    """Delete a document by ID. Returns True if deleted, False if not found."""
    # Fetch first to get file path for disk cleanup
    doc = await get_document(session, doc_id)
    if not doc:
        return False
    await session.execute(
        sa_delete(documents).where(documents.c.id == doc_id)
    )
    await session.commit()
    return True


async def count_documents(session, *, user_id: str | None = None) -> int:
    """Count documents, optionally filtered by user_id."""
    stmt = select(func.count()).select_from(documents)
    if user_id is not None:
        stmt = stmt.where(documents.c.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar() or 0
