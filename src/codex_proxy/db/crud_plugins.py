"""CRUD operations for plugin_registry and plugin_instances tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from .models import plugin_instances, plugin_registry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Plugin Registry (marketplace catalog) ─────────────────────────────────

async def register_plugin(session, *, plugin_id: str, name: str, version: str,
                          description: str | None = None, author: str | None = None,
                          download_url: str = "", checksum_sha256: str = "") -> dict:
    now = _now()
    await session.execute(
        plugin_registry.insert().values(
            id=plugin_id, name=name, version=version,
            description=description, author=author,
            download_url=download_url, checksum_sha256=checksum_sha256,
            downloads=0, created_at=now,
        )
    )
    await session.commit()
    return await get_registry_plugin(session, plugin_id)


async def get_registry_plugin(session, plugin_id: str) -> dict | None:
    result = await session.execute(
        select(plugin_registry).where(plugin_registry.c.id == plugin_id)
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_registry_plugins(session, *, limit: int = 50, offset: int = 0) -> list[dict]:
    result = await session.execute(
        select(plugin_registry).order_by(plugin_registry.c.downloads.desc())
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in result.mappings().all()]


async def increment_downloads(session, plugin_id: str) -> None:
    await session.execute(
        update(plugin_registry).where(plugin_registry.c.id == plugin_id)
        .values(downloads=plugin_registry.c.downloads + 1)
    )
    await session.commit()


# ── Plugin Instances (installed per user) ──────────────────────────────────

async def install_plugin(session, *, user_id: str, plugin_registry_id: str | None = None,
                         config_json: str = "{}") -> dict:
    iid = _new_id()
    now = _now()
    await session.execute(
        plugin_instances.insert().values(
            id=iid, user_id=user_id,
            plugin_registry_id=plugin_registry_id,
            config_json=config_json, is_enabled=True, installed_at=now,
        )
    )
    await session.commit()
    return await get_installed_plugin(session, iid)


async def get_installed_plugin(session, instance_id: str) -> dict | None:
    result = await session.execute(
        select(plugin_instances).where(plugin_instances.c.id == instance_id)
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_installed_plugins(session, user_id: str) -> list[dict]:
    result = await session.execute(
        select(plugin_instances).where(plugin_instances.c.user_id == user_id)
        .order_by(plugin_instances.c.installed_at.desc())
    )
    return [dict(row) for row in result.mappings().all()]


async def update_plugin_config(session, instance_id: str, config_json: str) -> dict | None:
    await session.execute(
        update(plugin_instances).where(plugin_instances.c.id == instance_id)
        .values(config_json=config_json)
    )
    await session.commit()
    return await get_installed_plugin(session, instance_id)


async def toggle_plugin(session, instance_id: str, enabled: bool) -> dict | None:
    await session.execute(
        update(plugin_instances).where(plugin_instances.c.id == instance_id)
        .values(is_enabled=enabled)
    )
    await session.commit()
    return await get_installed_plugin(session, instance_id)


async def uninstall_plugin(session, instance_id: str) -> bool:
    result = await session.execute(
        delete(plugin_instances).where(plugin_instances.c.id == instance_id)
    )
    await session.commit()
    return result.rowcount > 0
