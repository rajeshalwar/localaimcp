"""Export the live caches into committed fixtures.

This is how fixtures/cache/*.json is regenerated: warm the caches against the
real APIs, then export. Committed fixtures are what make the offline demo
(REPLAY_ONLY=true) reproducible from a fresh `git clone` -- a warm database
volume is not.

Refuses to export anything whose address is not on the public-landmark
allowlist, because these files ship in a public repo.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from mcp_solar import db

from . import allowlist

OUT = pathlib.Path("/app/fixtures/cache/seed.json")


async def main() -> int:
    allowed = allowlist.load()
    payload: dict[str, dict] = {"geocode": {}, "pvwatts": {}}
    skipped = []
    coords: set[tuple[float, float]] = set()

    async with (await db.pool()).connection() as conn:
        cur = await conn.execute("SELECT address_norm, response FROM geocode_cache")
        for address_norm, response in await cur.fetchall():
            matched = response.get("matched_address") or ""
            if not (allowlist.is_allowed(matched, allowed)
                    and allowlist.is_allowed(address_norm, allowed)):
                skipped.append(matched or address_norm)
                continue
            payload["geocode"][address_norm] = response
            coords.add(allowlist.rounded(response["lat"], response["lon"]))

        # A rounded coordinate is still a location. Export only those that
        # belong to an allowlisted address.
        cur = await conn.execute(
            "SELECT cache_key, lat_r, lon_r, params, response FROM pvwatts_cache")
        for key, lat_r, lon_r, params, response in await cur.fetchall():
            if "_SYNTHETIC" in (response or {}):
                skipped.append("synthetic pvwatts entry")
                continue
            if allowlist.rounded(lat_r, lon_r) not in coords:
                skipped.append(f"pvwatts at ({float(lat_r)}, {float(lon_r)})")
                continue
            payload["pvwatts"][key] = {
                "lat_r": float(lat_r), "lon_r": float(lon_r),
                "params": params, "response": response,
            }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"exported {len(payload['geocode'])} geocode and "
          f"{len(payload['pvwatts'])} pvwatts entries to {OUT}")
    if skipped:
        print(f"skipped {len(skipped)} entr(ies) not on the allowlist or synthetic:")
        for s in skipped:
            print("  -", s)
    await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
