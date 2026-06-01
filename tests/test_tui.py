"""Tests for TUI dashboard."""

from unittest.mock import patch

import pytest

from codex_proxy.config import ProviderConfig, ProxyConfig
from codex_proxy.server import configure


class TestCheckRich:
    def test_raises_without_rich(self):
        from codex_proxy.tui import _check_rich
        with patch.dict("sys.modules", {"rich": None}), \
             pytest.raises(ImportError, match="pip install codex-proxy\\[tui\\]"):
            _check_rich()


class TestRingHandler:
    def test_captures_records(self):
        import logging

        from codex_proxy.tui import _RingHandler
        handler = _RingHandler(5)
        logger = logging.getLogger("test_ring")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        for i in range(10):
            logger.info("msg %d", i)
        assert len(handler.records) == 5
        assert handler.records[0].message == "msg 5"
        logger.removeHandler(handler)

    def test_capacity_limit(self):
        import logging

        from codex_proxy.tui import _RingHandler
        handler = _RingHandler(3)
        for i in range(10):
            handler.emit(logging.LogRecord("t", logging.INFO, "", 0, f"m{i}", (), None))
        assert len(handler.records) == 3


class TestDashboard:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = ProxyConfig(provider=ProviderConfig(api_key="test-key"))
        configure(config)

    def test_render_returns_group(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        # Need rich installed to test rendering
        pytest.importorskip("rich")
        d = Dashboard(_state())
        result = d._render()
        assert result is not None

    def test_handle_key_quit(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        pytest.importorskip("rich")
        d = Dashboard(_state())
        assert d._handle_key("q") is True
        assert d._running is False

    def test_handle_key_clear(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        pytest.importorskip("rich")
        state = _state()
        state.store.put("r1", {"id": "r1"})
        assert state.store.size() == 1
        d = Dashboard(state)
        d._handle_key("c")
        assert state.store.size() == 0

    def test_handle_key_reload(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        pytest.importorskip("rich")
        d = Dashboard(_state())
        # Should not raise
        d._handle_key("r")

    def test_handle_key_compact(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        pytest.importorskip("rich")
        d = Dashboard(_state())
        # Should not raise
        d._handle_key("t")

    def test_handle_key_unknown(self):
        from codex_proxy.server import _state
        from codex_proxy.tui import Dashboard
        pytest.importorskip("rich")
        d = Dashboard(_state())
        assert d._handle_key("x") is False


class TestStartTui:
    def test_spawns_daemon_thread(self):
        import threading

        from codex_proxy.server import _state
        from codex_proxy.tui import start_tui

        pytest.importorskip("rich")
        barrier = threading.Barrier(2, timeout=5)

        def fake_run(self):
            barrier.wait()

        with patch("codex_proxy.tui.Dashboard.run", fake_run):
            start_tui(_state())
            barrier.wait()  # ensure thread has started
        threads = [t for t in threading.enumerate() if t.name == "codex-proxy-tui"]
        assert len(threads) == 1
        assert threads[0].daemon is True
