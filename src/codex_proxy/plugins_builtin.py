"""Built-in plugins for codex-proxy."""

from __future__ import annotations

import logging

from .plugins import Plugin, PluginContext

logger = logging.getLogger("codex-proxy")


class LoggingPlugin(Plugin):
    """Structured request/response logging plugin."""

    name = "logging"

    async def on_request(self, ctx: PluginContext) -> PluginContext:
        logger.info(
            "[plugin:logging] request id=%s method=%s model=%s provider=%s stream=%s",
            ctx.request_id, ctx.method, ctx.model, ctx.provider, ctx.stream,
        )
        return ctx

    async def on_response(self, ctx: PluginContext) -> None:
        logger.info(
            "[plugin:logging] response id=%s status=%d duration=%.1fms",
            ctx.request_id, ctx.status_code or 0, ctx.duration_ms or 0,
        )

    async def on_error(self, ctx: PluginContext) -> None:
        logger.error(
            "[plugin:logging] error id=%s status=%d error=%s",
            ctx.request_id, ctx.status_code or 0, ctx.error,
        )
