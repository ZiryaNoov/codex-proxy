"""CRUD operations for the users table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from .models import users


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


async def create_user(session, *, username: str, email: str | None,
                      password_hash: str, role: str = "user") -> dict:
    """Insert a new user. Returns the user record as dict."""
    uid = _new_id()
    now = _now()
    await session.execute(
        users.insert().values(
            id=uid, username=username, email=email,
            password_hash=password_hash, role=role,
            is_active=True, created_at=now, updated_at=now,
        )
    )
    await session.commit()
    return await get_user_by_id(session, uid)


async def get_user_by_id(session, user_id: str) -> dict | None:
    result = await session.execute(select(users).where(users.c.id == user_id))
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_by_username(session, username: str) -> dict | None:
    result = await session.execute(select(users).where(users.c.username == username))
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_by_email(session, email: str) -> dict | None:
    result = await session.execute(select(users).where(users.c.email == email))
    row = result.mappings().first()
    return dict(row) if row else None


async def list_users(session, *, limit: int = 50, offset: int = 0) -> list[dict]:
    result = await session.execute(
        select(users).order_by(users.c.created_at).limit(limit).offset(offset)
    )
    return [dict(row) for row in result.mappings().all()]


async def update_user(session, user_id: str, **fields) -> dict | None:
    fields["updated_at"] = _now()
    await session.execute(update(users).where(users.c.id == user_id).values(**fields))
    await session.commit()
    return await get_user_by_id(session, user_id)


async def deactivate_user(session, user_id: str) -> dict | None:
    return await update_user(session, user_id, is_active=False)


async def count_users(session) -> int:
    from sqlalchemy import func
    result = await session.execute(select(func.count()).select_from(users))
    return result.scalar() or 0
