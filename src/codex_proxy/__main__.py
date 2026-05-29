"""CLI entry point — `codex-proxy` or `python -m codex_proxy`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config, write_example_config, DEFAULT_CONFIG
from .server import run


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="codex-proxy",
        description="Responses API → Chat Completions bridge for Codex CLI",
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
    args = ap.parse_args()

    if args.init:
        path = write_example_config()
        print(f"Example config written to {path}")
        sys.exit(0)

    config = load_config(args.config and Path(args.config))

    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.port = args.port

    if args.print_config:
        print(f"  host:   {config.server.host}")
        print(f"  port:   {config.server.port}")
        print(f"  provider: {config.provider.display_name}")
        print(f"  base_url: {config.provider.base_url}")
        print(f"  models: {', '.join(config.provider.models)}")
        print(f"  api_key: {'***' if config.provider.effective_api_key() else '(empty)'}")
        sys.exit(0)

    if not config.provider.effective_api_key():
        print("WARNING: No API key configured.")
        print(f"  Set api_key or api_key_env in {DEFAULT_CONFIG}")
        print("  Or set CODEX_PROXY_API_KEY / OPENAI_API_KEY env var")

    run(config)


if __name__ == "__main__":
    main()
