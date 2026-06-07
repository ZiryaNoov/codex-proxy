"""CRUD operations for the api_keys table."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from .models import api_keys

# API key prefix for user-facing keys
KEY_PREFIX = "cpk"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _generate_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (full_key, key_hash, key_prefix)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}_{raw}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    prefix = full_key[:8]  # "cpk-ABCD..."
    return full_key, key_hash, prefix


def hash_key(key: str) -> str:
    """Hash an API key for lookup."""
    return hashlib.sha256(key.encode()).hexdigest()


async def create_api_key(session, *, user_id: str, name: str = "default") -> dict:
    """Create a new API key. Returns dict with 'key' (shown once) and key metadata."""
    full_key, key_hash, key_prefix = _generate_key()
    kid = _new_id()
    now = _now()
    await session.execute(
        api_keys.insert().values(
            id=kid, user_id=user_id, key_hash=key_hash,
            key_prefix=key_prefix, name=name,
            is_revoked=False, created_at=now,
        )
    )
    await session.commit()
    record = await get_key_by_id(session, kid)
    return {**record, "key": full_key}  # Full key returned only on creation


async def get_key_by_id(session, key_id: str) -> dict | None:
    result = await session.execute(select(api_keys).where(api_keys.c.id == key_id))
    row = result.mappings().first()
    return dict(row) if row else None


async def get_key_by_hash(session, key_hash: str) -> dict | None:
    """Look up an API key by its SHA-256 hash."""
    result = await session.execute(
        select(api_keys).where(api_keys.c.key_hash == key_hash, api_keys.c.is_revoked == False)  # noqa: E712
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def lookup_key(session, full_key: str) -> dict | None:
    """Look up an API key by the full key string."""
    return await get_key_by_hash(session, hash_key(full_key))


async def list_keys_by_user(session, user_id: str) -> list[dict]:
    result = await session.execute(
        select(api_keys).where(api_keys.c.user_id == user_id)
        .order_by(api_keys.c.created_at.desc())
    )
    return [dict(row) for row in result.mappings().all()]


async def revoke_key(session, key_id: str) -> dict | None:
    await session.execute(
        update(api_keys).where(api_keys.c.id == key_id)
        .values(is_revoked=True)
    )
    await session.commit()
    return await get_key_by_id(session, key_id)


async def touch_last_used(session, key_id: str) -> None:
    """Update last_used_at timestamp."""
    await session.execute(
        update(api_keys).where(api_keys.c.id == key_id)
        .values(last_used_at=_now())
    )
    # No commit — caller commits after the request


async def count_active_keys(session, user_id: str) -> int:
    from sqlalchemy import func
    result = await session.execute(
        select(func.count()).select_from(api_keys)
        .where(api_keys.c.user_id == user_id, api_keys.c.is_revoked == False)  # noqa: E712
    )
    return result.scalar() or 0
