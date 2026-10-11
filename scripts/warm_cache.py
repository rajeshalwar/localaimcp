"""Re-fetch the seeded addresses so the cache stays fresh.

NOTE: this makes outbound requests. It is wired to warm-cache.timer, which is
deliberately not enabled -- see systemd/warm-cache.timer.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

from mcp_solar import db
from mcp_solar.tools.geocode import geocode_address
from mcp_solar.tools.production import estimate_solar_production

SEEDS = pathlib.Path("/app/fixtures/seed_addresses.txt")


async def main() -> int:
    if not SEEDS.exists():
        print("no seed list; nothing to warm")
        return 0
    for line in SEEDS.read_text().splitlines():
        address = line.strip()
        if not address or address.startswith("#"):
            continue
        located = await geocode_address(address)
        if "error" in located:
            print("skip", address, "->", located["error"])
            continue
        await estimate_solar_production(lat=located["lat"], lon=located["lon"])
        print("warmed", located.get("matched_address") or address)
    await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
