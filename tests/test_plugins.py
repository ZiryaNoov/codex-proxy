"""Tests for plugin system."""

import asyncio

from codex_proxy.plugins import Plugin, PluginContext, PluginRegistry


def _run(coro):
    return asyncio.run(coro)


class TestPluginBase:
    def test_noop_methods(self):
        p = Plugin()
        ctx = PluginContext(request_id="t", method="http", model="m",
                            provider="p", api_key_masked="***", stream=False)
        result = _run(p.on_request(ctx))
        assert result is ctx


class TestPluginContext:
    def test_defaults(self):
        ctx = PluginContext(request_id="r1", method="http", model="gpt",
                            provider="zai", api_key_masked="***", stream=True)
        assert ctx.status_code is None
        assert ctx.error is None
        assert ctx.duration_ms is None
        assert ctx.metadata == {}


class TestPluginRegistry:
    def test_load_and_list(self):
        reg = PluginRegistry()
        reg.load(["codex_proxy.plugins_builtin.LoggingPlugin"])
        assert reg.list_plugins() == ["logging"]

    def test_load_invalid_path(self):
        reg = PluginRegistry()
        reg.load(["nonexistent.module.BadClass"])
        assert reg.list_plugins() == []

    def test_on_request_chains(self):
        class AddMeta(Plugin):
            name = "add_meta"
            async def on_request(self, ctx):
                ctx.metadata["added"] = True
                return ctx

        reg = PluginRegistry()
        reg._plugins.append(AddMeta())
        ctx = PluginContext(request_id="t", method="http", model="m",
                            provider="p", api_key_masked="***", stream=False)
        result = _run(reg.on_request(ctx))
        assert result.metadata["added"] is True

    def test_broken_plugin_does_not_crash(self):
        class BadPlugin(Plugin):
            name = "bad"
            async def on_request(self, ctx):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg._plugins.append(BadPlugin())
        ctx = PluginContext(request_id="t", method="http", model="m",
                            provider="p", api_key_masked="***", stream=False)
        result = _run(reg.on_request(ctx))
        assert result.request_id == "t"

    def test_reset_clears(self):
        reg = PluginRegistry()
        reg.load(["codex_proxy.plugins_builtin.LoggingPlugin"])
        assert len(reg.list_plugins()) == 1
        reg.reset()
        assert reg.list_plugins() == []

    def test_on_response_and_error_called(self):
        calls = []

        class TrackPlugin(Plugin):
            name = "track"
            async def on_response(self, ctx):
                calls.append(("response", ctx.request_id))
            async def on_error(self, ctx):
                calls.append(("error", ctx.request_id))

        reg = PluginRegistry()
        reg._plugins.append(TrackPlugin())
        ctx = PluginContext(request_id="r1", method="http", model="m",
                            provider="p", api_key_masked="***", stream=False)
        _run(reg.on_response(ctx))
        _run(reg.on_error(ctx))
        assert calls == [("response", "r1"), ("error", "r1")]


class TestLoggingPlugin:
    def test_on_request(self):
        from codex_proxy.plugins_builtin import LoggingPlugin
        p = LoggingPlugin()
        ctx = PluginContext(request_id="r1", method="http", model="glm",
                            provider="zai", api_key_masked="***", stream=True)
        _run(p.on_request(ctx))

    def test_on_response(self):
        from codex_proxy.plugins_builtin import LoggingPlugin
        p = LoggingPlugin()
        ctx = PluginContext(request_id="r1", method="http", model="glm",
                            provider="zai", api_key_masked="***", stream=False)
        ctx.status_code = 200
        ctx.duration_ms = 150.0
        _run(p.on_response(ctx))

    def test_on_error(self):
        from codex_proxy.plugins_builtin import LoggingPlugin
        p = LoggingPlugin()
        ctx = PluginContext(request_id="r1", method="http", model="glm",
                            provider="zai", api_key_masked="***", stream=False)
        ctx.status_code = 500
        ctx.error = "timeout"
        _run(p.on_error(ctx))
