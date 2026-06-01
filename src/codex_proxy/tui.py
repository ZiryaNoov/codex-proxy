"""Rich TUI dashboard for codex-proxy — live metrics, circuit breaker, log tail."""

from __future__ import annotations

import logging
import platform
import sys
import threading
import time
from collections import deque

from . import __version__


def _check_rich():
    """Import guard — raises with install hint if rich is not available."""
    try:
        import rich  # noqa: F401
    except ImportError:
        raise ImportError(
            "Rich is required for TUI mode. Install with: pip install codex-proxy[tui]"
        ) from None


class _RingHandler(logging.Handler):
    """Logging handler that keeps the last N records in a deque."""

    def __init__(self, capacity: int = 50):
        super().__init__()
        self.records: deque[logging.LogRecord] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _read_key() -> str | None:
    """Non-blocking stdin read. Returns key char or None."""
    if platform.system() == "Windows":
        import msvcrt
        if msvcrt.kbhit():
            return msvcrt.getwch()
        return None
    else:
        import select
        import termios  # type: ignore[import-not-found]
        import tty  # type: ignore[import-not-found]

        if not sys.stdin.isatty():
            return None
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore[attr-defined]
        try:
            tty.setcbreak(fd)  # type: ignore[attr-defined]
            readable, _, _ = select.select([sys.stdin], [], [], 0)
            if readable:
                return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore[attr-defined]
        return None


class Dashboard:
    """Rich Live dashboard rendering proxy state."""

    def __init__(self, state):

        self.state = state
        self._log_handler = _RingHandler(50)
        self._log_handler.setLevel(logging.DEBUG)
        logging.getLogger("codex-proxy").addHandler(self._log_handler)
        self._running = False
        self._last_action: str = ""
        self._last_action_time: float = 0.0

    def _render(self):
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        state = self.state
        now = time.time()
        uptime = int(now - state.start_time)
        hours, remainder = divmod(uptime, 3600)
        mins, secs = divmod(remainder, 60)

        # Header
        header = Text(
            f"  codex-proxy v{__version__}   uptime {hours:02d}:{mins:02d}:{secs:02d}  ",
            style="bold white on blue",
        )

        # Provider panel
        prov = state.config.provider
        prov_table = Table(show_header=False, box=None, padding=(0, 1))
        prov_table.add_column("key", style="dim")
        prov_table.add_column("val")
        prov_table.add_row("name", prov.display_name)
        prov_table.add_row("url", prov.base_url)
        prov_table.add_row("model", prov.default_model)
        prov_table.add_row("models", ", ".join(prov.models))
        provider_panel = Panel(prov_table, title="Provider", border_style="cyan")

        # Circuit breaker panel
        cb = state.circuit_breaker
        if cb:
            cb_status = cb.get_status()
            state_str = cb_status.get("state", "UNKNOWN")
            state_colors = {"closed": "green", "open": "red", "half_open": "yellow"}
            color = state_colors.get(state_str, "white")

            cb_table = Table(show_header=False, box=None, padding=(0, 1))
            cb_table.add_column("key", style="dim")
            cb_table.add_column("val")
            cb_table.add_row("state", Text(state_str, style=f"bold {color}"))
            cb_table.add_row("failures", str(cb_status.get("failure_count", 0)))
            cb_table.add_row("threshold", str(cb_status.get("failure_threshold", 0)))
            if state_str == "open":
                rec = cb_status.get("recovery_timeout", 30)
                last_fail = cb_status.get("last_failure_time", 0)
                remaining = max(0, rec - (now - last_fail))
                cb_table.add_row("recovery in", f"{remaining:.0f}s")
            else:
                cb_table.add_row("recovery", f"{cb_status.get('recovery_timeout', 0)}s")
            cb_panel = Panel(cb_table, title="Circuit Breaker", border_style=color)
        else:
            cb_panel = Panel(Text("disabled", style="dim"), title="Circuit Breaker",
                             border_style="dim")

        # Metrics panel
        total = state.request_count or 1
        success_rate = (state.success_count / total) * 100 if total > 1 else 0

        met_table = Table(show_header=False, box=None, padding=(0, 1))
        met_table.add_column("key", style="dim")
        met_table.add_column("val")
        met_table.add_row("requests", str(state.request_count))
        met_table.add_row("success", str(state.success_count))
        met_table.add_row("failures", str(state.failure_count))
        met_table.add_row("success rate", f"{success_rate:.1f}%")
        if state.last_request_time:
            ago = now - state.last_request_time
            met_table.add_row("last req", f"{ago:.1f}s ago")
        else:
            met_table.add_row("last req", "never")
        met_table.add_row("store", f"{state.store.size()}/{state.store.max_entries}")
        if state.plugin_registry:
            met_table.add_row("plugins", ", ".join(state.plugin_registry.list_plugins()))
        metrics_panel = Panel(met_table, title="Metrics", border_style="green")

        # Key Pool panel
        kr = state.key_rotator
        if kr:
            kp_table = Table(show_header=False, box=None, padding=(0, 1))
            kp_table.add_column("key", style="dim")
            kp_table.add_column("val")
            for ks in kr.get_status():
                state_colors = {"closed": "green", "open": "red", "half_open": "yellow"}
                sc = state_colors.get(ks["state"], "white")
                kp_table.add_row(
                    ks["key"],
                    Text(ks["state"], style=sc) if ks["errors"] == 0
                    else Text(f"{ks['state']} (err:{ks['errors']})", style=sc),
                )
            key_pool_panel = Panel(kp_table, title=f"Key Pool ({len(kr._keys)})",
                                   border_style="magenta")
        else:
            key_pool_panel = None

        # Log tail panel
        log_lines = []
        for rec in list(self._log_handler.records)[-10:]:
            level_colors = {"DEBUG": "dim", "INFO": "blue", "WARNING": "yellow",
                            "ERROR": "red", "CRITICAL": "bold red"}
            color = level_colors.get(rec.levelname, "")
            ts = time.strftime("%H:%M:%S", time.localtime(rec.created))
            log_lines.append(Text(f"  {ts} [{rec.levelname}] {rec.message}",
                                  style=color))
        log_text = Text("\n").join(log_lines) if log_lines else Text("  (no logs yet)",
                                                                      style="dim")
        log_panel = Panel(log_text, title="Logs", border_style="blue",
                          height=12)

        # Hotkeys + action feedback
        hotkeys = Text("  r=reload   c=clear store   t=compact   q=quit",
                       style="bold white on black")
        action = Text("")
        if self._last_action and (time.time() - self._last_action_time) < 3.0:
            action = Text(f"  >> {self._last_action}", style="bold green")

        panels = [header, provider_panel, cb_panel, metrics_panel]
        if key_pool_panel:
            panels.append(key_pool_panel)
        panels.extend([log_panel, hotkeys, action])
        return Group(*panels)

    def _handle_key(self, key: str) -> bool:
        """Handle a hotkey press. Returns True if should quit."""
        if key == "q":
            self._running = False
            return True
        elif key == "r":
            from .server import _state, reload_config_internal
            state = _state()
            try:
                reload_config_internal(state)
                self._last_action = "Config reloaded!"
                self._last_action_time = time.time()
                logging.getLogger("codex-proxy").info("Config and services reloaded via TUI")
            except Exception as e:
                self._last_action = f"Reload FAILED: {e}"
                self._last_action_time = time.time()
                logging.getLogger("codex-proxy").error("Reload failed: %s", e)
        elif key == "c":
            from .server import _state
            state = _state()
            cleared = state.store.size()
            state.store._store.clear()
            self._last_action = f"Store cleared ({cleared} entries removed)"
            self._last_action_time = time.time()
            logging.getLogger("codex-proxy").info("Store cleared via TUI")
        elif key == "t":
            from .server import _state
            state = _state()
            self._last_action = (
                f"Compaction: enabled={state.config.compaction.enabled}, "
                f"max={state.config.compaction.max_messages}, "
                f"keep_last={state.config.compaction.keep_last}"
            )
            self._last_action_time = time.time()
            logging.getLogger("codex-proxy").info(
                "Compaction: enabled=%s, max=%d, keep_last=%d",
                state.config.compaction.enabled,
                state.config.compaction.max_messages,
                state.config.compaction.keep_last,
            )
        return False

    def run(self) -> None:
        """Main dashboard loop — runs in daemon thread."""
        from rich.live import Live

        self._running = True
        with Live(self._render(), refresh_per_second=2, screen=True) as live:
            while self._running:
                key = _read_key()
                if key and self._handle_key(key.lower()):
                    break
                live.update(self._render())
                time.sleep(0.1)

        logging.getLogger("codex-proxy").removeHandler(self._log_handler)


def start_tui(state) -> None:
    """Spawn the TUI dashboard in a daemon thread."""
    _check_rich()

    dashboard = Dashboard(state)
    thread = threading.Thread(target=dashboard.run, daemon=True, name="codex-proxy-tui")
    thread.start()
    logging.getLogger("codex-proxy").info("TUI dashboard started")
