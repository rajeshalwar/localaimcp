"""Load committed fixtures into the caches so the demo runs with no network.

A warm database volume does not survive `git clone`; committed fixtures do.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from mcp_solar import db

FIXTURES = pathlib.Path("/app/fixtures/cache")


async def main() -> int:
    if not FIXTURES.exists():
        print(f"no fixtures at {FIXTURES}")
        return 1
    geo = pv = 0
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text())
        for key, record in (payload.get("geocode") or {}).items():
            await db.geocode_cache_put(key, record, seeded=True)
            geo += 1
        for key, entry in (payload.get("pvwatts") or {}).items():
            await db.pvwatts_cache_put(key, entry["lat_r"], entry["lon_r"],
                                       entry["params"], entry["response"], seeded=True)
            pv += 1
    print(f"seeded {geo} geocode and {pv} pvwatts entries from {FIXTURES}")
    await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
