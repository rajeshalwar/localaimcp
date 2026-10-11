"""Verify the NREL key works and that PVWatts still returns the shape we parse.

This exists because the PVWatts integration could not be tested at build time:
developer.nrel.gov was unreachable from the environment the code was written in.
Run it once before trusting any production number.
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp_solar.config import settings
from mcp_solar.tools.production import estimate_solar_production

EXPECTED = ["ac_annual_kwh", "ac_monthly_kwh", "solrad_annual", "capacity_factor"]


async def main() -> int:
    if not settings.nrel_api_key:
        print("FAIL: NREL_API_KEY is not set in the container environment.")
        return 2
    print(f"key present ({settings.nrel_api_key[:4]}…{settings.nrel_api_key[-4:]}), calling PVWatts…")

    # Texas State Capitol.
    out = await estimate_solar_production(lat=30.2764, lon=-97.7397, system_capacity_kw=7.0)
    if "error" in out:
        print("FAIL:", out["error"])
        return 1

    missing = [k for k in EXPECTED if k not in out]
    if missing:
        print("FAIL: response is missing", missing)
        print(json.dumps(out, indent=2)[:800])
        return 1

    print(json.dumps({k: out[k] for k in EXPECTED if k != "ac_monthly_kwh"}, indent=2))
    print("months returned:", len(out["ac_monthly_kwh"]))
    print("coordinates transmitted:", out["lat_sent"], out["lon_sent"], "(rounded, as designed)")
    print("weather station:", out.get("weather_station"), f"{out.get('weather_distance_m')} m away")
    ok = len(out["ac_monthly_kwh"]) == 12 and out["ac_annual_kwh"] > 0
    print("\nPASS" if ok else "\nFAIL: implausible values")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
