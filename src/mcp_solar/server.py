"""The MCP server.

Same code, two transports:
  --http   Streamable HTTP on :8000/mcp  (containers talk over the network, and
           any MCP client -- Claude Desktop, Cline, your own -- can connect)
  --stdio  classic stdio, for a local client that spawns us as a child process

SDK note: this targets mcp >= 2.0, where the class formerly known as FastMCP is
called MCPServer. If you are reading a tutorial that says `FastMCP`, it is the
same object under its pre-2.0 name -- the decorator API is unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import db, prompts, resources
from .config import settings
from .tools import register_all

log = logging.getLogger("mcp_solar")


def build(profile: str) -> tuple[MCPServer, list[str]]:
    mcp = MCPServer("solar", version="0.1.0")
    names = register_all(mcp, profile=profile)
    resources.register(mcp)
    prompts.register(mcp)
    return mcp, names


def _security(extra_hosts: list[str]) -> TransportSecuritySettings:
    """DNS-rebinding protection defaults to ON with an EMPTY allow-list, which
    rejects `Host: appliance:8000` from another container. Everything here is
    on an internal network with no route off-box, so we allow the service names
    we actually use rather than disabling the protection outright.
    """
    hosts: list[str] = []
    for h in ["appliance", "localhost", "127.0.0.1", "0.0.0.0", *extra_hosts]:
        h = h.strip()
        if h:
            # "host:*" is the SDK's port wildcard. Pinning a single port breaks
            # the moment compose maps the service to a different host port.
            hosts += [h, f"{h}:*"]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=["*"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mcp-solar")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--http", action="store_true", help="Streamable HTTP (default)")
    mode.add_argument("--stdio", action="store_true", help="stdio transport")
    ap.add_argument("--host", default=os.environ.get("MCP_BIND", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    ap.add_argument("--profile", default=settings.tool_profile,
                    choices=["granular", "composite", "all"])
    ap.add_argument("--skip-migrate", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.skip_migrate:
        applied = asyncio.run(db.migrate())
        log.info("migrations applied: %s", ", ".join(applied) or "none")

    mcp, names = build(args.profile)
    log.info("tool profile %r -> %d tools: %s", args.profile, len(names), ", ".join(names))
    if settings.replay_only:
        log.warning("REPLAY_ONLY is set: no request will leave this machine.")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        log.info("Streamable HTTP on http://%s:%d/mcp", args.host, args.port)
        mcp.run(
            transport="streamable-http",
            host=args.host, port=args.port,
            streamable_http_path="/mcp",
            transport_security=_security(os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
