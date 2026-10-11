"""Coordinates -> annual solar production, via NREL PVWatts v8.

Coordinates are rounded to 3 decimals (~110 m) BEFORE transmission. PVWatts
resolves to a ~4 km solar resource grid, so this costs nothing in accuracy and
means NREL never receives a precise location.
"""
from __future__ import annotations

import hashlib
import json

from . import tool
from .. import db, net
from ..config import settings

ARRAY_TYPES = {0: "fixed open rack", 1: "fixed roof mount", 2: "1-axis tracking",
               3: "1-axis backtracking", 4: "2-axis tracking"}


def cache_key(params: dict) -> str:
    """Stable key over everything that affects the answer, minus the secret."""
    material = {k: v for k, v in sorted(params.items()) if k != "api_key"}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


@tool(profiles=("granular", "all"))
async def estimate_solar_production(
    lat: float,
    lon: float,
    system_capacity_kw: float = 7.0,
    tilt: float | None = None,
    azimuth: float = 180.0,
    array_type: int = 1,
    losses: float = 14.0,
) -> dict:
    """Estimate how many kWh a solar array at these coordinates would produce in
    a year, using NREL PVWatts. tilt defaults to the site latitude."""
    if lat is None or lon is None:
        return {"error": "lat and lon are required",
                "hint": "Call geocode_address first to turn the address into coordinates."}

    # P3: round before transmitting, not after.
    lat_r = round(float(lat), settings.coord_precision)
    lon_r = round(float(lon), settings.coord_precision)
    tilt_v = abs(lat_r) if tilt is None else float(tilt)

    params = {
        "lat": lat_r, "lon": lon_r,
        "system_capacity": float(system_capacity_kw),
        "azimuth": float(azimuth), "tilt": round(tilt_v, 2),
        "array_type": int(array_type), "module_type": 0,
        "losses": float(losses), "timeframe": "monthly",
    }
    key = cache_key(params)

    cached = await db.pvwatts_cache_get(key)
    if cached is not None:
        await net.log_cache_hit("nrel", settings.pvwatts_url, params)
        return {**cached, "cached": True}

    if not settings.nrel_api_key:
        return {"error": "NREL_API_KEY is not set",
                "hint": "Tell the user to add a free key from developer.nlr.gov to .env."}

    try:
        payload = await net.fetch_json(
            service="nrel", url=settings.pvwatts_url,
            params={**params, "api_key": settings.nrel_api_key},
            redact=("api_key",),
        )
    except net.ReplayMiss as exc:
        return {"error": str(exc),
                "hint": "These coordinates are not in the offline cache. Use a seeded demo address."}
    except Exception as exc:
        return {"error": f"PVWatts unavailable: {exc}",
                "hint": "Tell the user the solar API is unreachable; do not invent production numbers."}

    if payload.get("errors"):
        return {"error": "; ".join(payload["errors"]),
                "hint": "Check the coordinates are within the US and the system size is realistic."}

    out = payload.get("outputs") or {}
    station = payload.get("station_info") or {}
    result = {
        "ac_annual_kwh": round(out.get("ac_annual", 0.0), 1),
        "ac_monthly_kwh": [round(v, 1) for v in (out.get("ac_monthly") or [])],
        "solrad_annual": round(out.get("solrad_annual", 0.0), 3),
        "capacity_factor": round(out.get("capacity_factor", 0.0), 2),
        "system_capacity_kw": float(system_capacity_kw),
        "tilt": round(tilt_v, 2),
        "azimuth": float(azimuth),
        "array_type": ARRAY_TYPES.get(int(array_type), str(array_type)),
        "lat_sent": lat_r, "lon_sent": lon_r,
        "weather_station": station.get("location"),
        "weather_distance_m": station.get("distance"),
    }
    await db.pvwatts_cache_put(key, lat_r, lon_r, params, result)
    return {**result, "cached": False}
