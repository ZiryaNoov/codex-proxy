"""CLI entry point — `codex-proxy` or `python -m codex_proxy`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, load_config, write_example_config
from .server import run


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="codex-proxy",
        description="Responses API to Chat Completions bridge for Codex CLI",
    )
    ap.add_argument("--config", "-c", type=str, default=None,
                    help=f"Config file path (default: {DEFAULT_CONFIG})")
    ap.add_argument("--host", type=str, default=None,
                    help="Override bind host")
    ap.add_argument("--port", "-p", type=int, default=None,
                    help="Override bind port")
    ap.add_argument("--init", action="store_true",
                    help="Write example config and exit")
    ap.add_argument("--print-config", action="store_true",
                    help="Print resolved config and exit")
    ap.add_argument("--tui", "-t", action="store_true",
                    help="Launch interactive Rich TUI dashboard")
    args = ap.parse_args()

    if args.init:
        path = write_example_config()
        print(f"Example config written to {path}")
        sys.exit(0)

    config = load_config(args.config and Path(args.config))

    if args.host is not None:
        config.server.host = args.host
    if args.port is not None:
        config.server.port = args.port

    if args.print_config:
        print(f"  host:   {config.server.host}")
        print(f"  port:   {config.server.port}")
        print(f"  provider: {config.provider.display_name}")
        print(f"  base_url: {config.provider.base_url}")
        print(f"  models: {', '.join(config.provider.models)}")
        print(f"  api_key: {'***' if config.provider.effective_api_key() else '(empty)'}")
        print(f"  key_pool: {len(config.provider.effective_api_keys())} key(s)")
        print(f"  circuit_breaker: {'enabled' if config.circuit_breaker.enabled else 'disabled'} (threshold={config.circuit_breaker.failure_threshold}, timeout={config.circuit_breaker.recovery_timeout}s)")
        print(f"  compaction: {'enabled' if config.compaction.enabled else 'disabled'} (max_messages={config.compaction.max_messages}, keep_last={config.compaction.keep_last})")
        print(f"  plugins: {'enabled' if config.plugins.enabled else 'disabled'} ({len(config.plugins.plugins)} configured)")
        print(f"  server: max_retries={config.server.max_retries}, retry_delay={config.server.retry_delay}s, connect_timeout={config.server.connect_timeout}s, read_timeout={config.server.read_timeout}s")
        print(f"  rate_limit: {'enabled' if config.rate_limit.enabled else 'disabled'} (max={config.rate_limit.max_requests}/{config.rate_limit.window_seconds}s)")
        print(f"  admin_token: {'***' if config.server.admin_token else '(empty)'}")
        print(f"  cors_origins: {config.server.cors_origins or '(none)'}")
        print(f"  max_request_body: {config.server.max_request_body_bytes} bytes")
        sys.exit(0)

    if not config.provider.effective_api_key():
        print("WARNING: No API key configured.")
        print(f"  Set api_key or api_key_env in {DEFAULT_CONFIG}")
        print("  Or set CODEX_PROXY_API_KEY / OPENAI_API_KEY env var")

    run(config, tui=args.tui)


if __name__ == "__main__":
    main()
