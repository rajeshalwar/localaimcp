"""MCP resources -- context a client can pull without spending a tool call."""
from __future__ import annotations

import json

from . import db


def register(mcp) -> None:
    @mcp.resource("solar://assessments/recent")
    async def recent_assessments() -> str:
        """The 10 most recent solar assessments stored on this machine."""
        rows = await db.list_assessments(limit=10)
        return json.dumps(rows, indent=2, default=str)
