"""Plugin system — hook-based extensibility for codex-proxy."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("codex-proxy")


@dataclass
class PluginContext:
    """Safe context passed to plugin hooks."""

    request_id: str
    method: str  # "http" or "ws"
    model: str
    provider: str
    api_key_masked: str
    stream: bool
    status_code: int | None = None
    error: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Plugin:
    """Base class for plugins. Override only the hooks you need."""

    name: str = "unnamed"

    async def on_startup(self, config: Any) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def on_request(self, ctx: PluginContext) -> PluginContext:
        return ctx

    async def on_response(self, ctx: PluginContext) -> None:
        pass

    async def on_error(self, ctx: PluginContext) -> None:
        pass


class PluginRegistry:
    """Loads and manages plugins from dotted module paths."""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []

    def load(self, plugin_paths: list[str]) -> None:
        """Load plugins from dotted module.class paths."""
        for path in plugin_paths:
            try:
                module_path, class_name = path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                instance: Plugin = cls()
                instance.name = getattr(instance, "name", class_name)
                self._plugins.append(instance)
                logger.info("Plugin loaded: %s", instance.name)
            except Exception as e:
                logger.error("Failed to load plugin %s: %s", path, e)

    async def on_startup(self, config: Any) -> None:
        for p in self._plugins:
            try:
                await p.on_startup(config)
            except Exception as e:
                logger.error("Plugin %s on_startup error: %s", p.name, e)

    async def on_shutdown(self) -> None:
        for p in self._plugins:
            try:
                await p.on_shutdown()
            except Exception as e:
                logger.error("Plugin %s on_shutdown error: %s", p.name, e)

    async def on_request(self, ctx: PluginContext) -> PluginContext:
        for p in self._plugins:
            try:
                ctx = await p.on_request(ctx)
            except Exception as e:
                logger.error("Plugin %s on_request error: %s", p.name, e)
        return ctx

    async def on_response(self, ctx: PluginContext) -> None:
        for p in self._plugins:
            try:
                await p.on_response(ctx)
            except Exception as e:
                logger.error("Plugin %s on_response error: %s", p.name, e)

    async def on_error(self, ctx: PluginContext) -> None:
        for p in self._plugins:
            try:
                await p.on_error(ctx)
            except Exception as e:
                logger.error("Plugin %s on_error error: %s", p.name, e)

    def list_plugins(self) -> list[str]:
        return [p.name for p in self._plugins]

    def reset(self) -> None:
        self._plugins.clear()
