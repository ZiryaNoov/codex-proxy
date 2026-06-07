"""CRUD operations for providers, provider_keys, and models tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from .models import models, provider_keys, providers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Providers ─────────────────────────────────────────────────────────────

async def create_provider(session, *, name: str, display_name: str,
                          base_url: str, adapter_name: str,
                          extra_headers: dict | None = None,
                          priority: int = 0) -> dict:
    pid = _new_id()
    now = _now()
    import json
    await session.execute(
        providers.insert().values(
            id=pid, name=name, display_name=display_name,
            base_url=base_url, adapter_name=adapter_name,
            extra_headers=json.dumps(extra_headers or {}),
            is_enabled=True, priority=priority,
            created_at=now, updated_at=now,
        )
    )
    await session.commit()
    return await get_provider_by_id(session, pid)


async def get_provider_by_id(session, provider_id: str) -> dict | None:
    result = await session.execute(select(providers).where(providers.c.id == provider_id))
    row = result.mappings().first()
    return dict(row) if row else None


async def get_provider_by_name(session, name: str) -> dict | None:
    result = await session.execute(select(providers).where(providers.c.name == name))
    row = result.mappings().first()
    return dict(row) if row else None


async def list_providers(session, *, enabled_only: bool = False) -> list[dict]:
    stmt = select(providers).order_by(providers.c.priority)
    if enabled_only:
        stmt = stmt.where(providers.c.is_enabled == True)  # noqa: E712
    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def update_provider(session, provider_id: str, **fields) -> dict | None:
    fields["updated_at"] = _now()
    if "extra_headers" in fields and isinstance(fields["extra_headers"], dict):
        import json
        fields["extra_headers"] = json.dumps(fields["extra_headers"])
    await session.execute(update(providers).where(providers.c.id == provider_id).values(**fields))
    await session.commit()
    return await get_provider_by_id(session, provider_id)


async def delete_provider(session, provider_id: str) -> bool:
    # Cascade: delete provider keys and models first
    await session.execute(delete(provider_keys).where(provider_keys.c.provider_id == provider_id))
    await session.execute(delete(models).where(models.c.provider_id == provider_id))
    result = await session.execute(delete(providers).where(providers.c.id == provider_id))
    await session.commit()
    return result.rowcount > 0


# ── Provider Keys ─────────────────────────────────────────────────────────

async def add_provider_key(session, *, provider_id: str, encrypted_key: str,
                           key_prefix: str) -> dict:
    kid = _new_id()
    now = _now()
    await session.execute(
        provider_keys.insert().values(
            id=kid, provider_id=provider_id,
            encrypted_key=encrypted_key, key_prefix=key_prefix,
            is_enabled=True, circuit_state="closed",
            failure_count=0, success_count=0, created_at=now,
        )
    )
    await session.commit()
    return dict((await session.execute(
        select(provider_keys).where(provider_keys.c.id == kid)
    )).mappings().first())


async def list_provider_keys(session, provider_id: str) -> list[dict]:
    result = await session.execute(
        select(provider_keys).where(provider_keys.c.provider_id == provider_id)
    )
    return [dict(row) for row in result.mappings().all()]


async def get_enabled_provider_keys(session, provider_id: str) -> list[dict]:
    result = await session.execute(
        select(provider_keys)
        .where(provider_keys.c.provider_id == provider_id, provider_keys.c.is_enabled == True)  # noqa: E712
    )
    return [dict(row) for row in result.mappings().all()]


async def update_provider_key(session, key_id: str, **fields) -> None:
    await session.execute(
        update(provider_keys).where(provider_keys.c.id == key_id).values(**fields)
    )
    # No commit — caller batches updates


async def record_key_success(session, key_id: str) -> None:
    now = _now()
    await session.execute(
        update(provider_keys).where(provider_keys.c.id == key_id).values(
            success_count=provider_keys.c.success_count + 1,
            failure_count=0,
            circuit_state="closed",
            last_used_at=now,
        )
    )


async def record_key_failure(session, key_id: str) -> None:
    await session.execute(
        update(provider_keys).where(provider_keys.c.id == key_id).values(
            failure_count=provider_keys.c.failure_count + 1,
            last_used_at=_now(),
        )
    )


# ── Models ────────────────────────────────────────────────────────────────

async def create_model(session, *, provider_id: str, model_id: str,
                       display_name: str | None = None,
                       input_price_per_million: float = 0.0,
                       output_price_per_million: float = 0.0) -> dict:
    mid = _new_id()
    await session.execute(
        models.insert().values(
            id=mid, provider_id=provider_id, model_id=model_id,
            display_name=display_name or model_id,
            input_price_per_million=input_price_per_million,
            output_price_per_million=output_price_per_million,
            is_enabled=True,
        )
    )
    await session.commit()
    return dict((await session.execute(
        select(models).where(models.c.id == mid)
    )).mappings().first())


async def get_model(session, provider_id: str, model_id: str) -> dict | None:
    result = await session.execute(
        select(models).where(
            models.c.provider_id == provider_id, models.c.model_id == model_id
        )
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_models_by_provider(session, provider_id: str) -> list[dict]:
    result = await session.execute(
        select(models).where(models.c.provider_id == provider_id)
    )
    return [dict(row) for row in result.mappings().all()]


async def get_model_pricing(session, model_id: str) -> dict | None:
    """Get pricing for a model across all providers (returns first match)."""
    result = await session.execute(
        select(models).where(models.c.model_id == model_id).limit(1)
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def seed_model_pricing(session, pricing_data: dict[str, tuple[float, float]],
                             default_provider_id: str) -> int:
    """Seed pricing data into models table. Returns count of models inserted."""
    count = 0
    for model_id, (input_price, output_price) in pricing_data.items():
        existing = await get_model(session, default_provider_id, model_id)
        if not existing:
            await create_model(
                session, provider_id=default_provider_id, model_id=model_id,
                input_price_per_million=input_price,
                output_price_per_million=output_price,
            )
            count += 1
    return count
