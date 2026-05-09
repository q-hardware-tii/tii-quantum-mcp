"""CLI entry point for tii-q-cloud-mcp."""

from __future__ import annotations

import argparse
import sys


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP stdio server."""
    from .server import run_server

    run_server()


def _cmd_check_auth(args: argparse.Namespace) -> None:
    """Verify that the API token works by calling the server version endpoint."""
    from .client import get_client

    try:
        client = get_client()
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        client.check_client_server_qibo_versions()
        print(f"✓ Authentication successful. Connected to {client.base_url}")
    except RuntimeError as exc:
        print(f"✗ Version check failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"✗ Connection error: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tii-q-cloud-mcp",
        description="MCP server for submitting quantum circuits to the TII Q-Cloud.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # serve subcommand
    srv = sub.add_parser("serve", help="Start the MCP server (stdio transport).")
    srv.set_defaults(func=_cmd_serve)

    # check-auth subcommand
    auth = sub.add_parser("check-auth", help="Verify API token and server connectivity.")
    auth.set_defaults(func=_cmd_check_auth)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
