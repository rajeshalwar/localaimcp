"""Address -> coordinates, via the US Census geocoder.

This is one of only two things in the whole stack that touches the network,
and it is the one that carries the user's address. We cache aggressively and
we store only a trimmed record: the Census response also carries census-block
identifiers, which are far more identifying than a street address and have no
business sitting in a public repo's fixtures.
"""
from __future__ import annotations

import re

from . import tool
from .. import db, net
from ..config import settings

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^A-Z0-9 ]")


def normalize(address: str) -> str:
    """Cache key for an address.

    Punctuation is stripped, not just whitespace. "San Antonio TX" and
    "San Antonio, TX" are the same place, but keying on punctuation made them
    different rows -- which in REPLAY_ONLY mode turned one missing comma into a
    failed demo. Collisions between genuinely different addresses are not a
    realistic risk at this granularity.
    """
    return _WS.sub(" ", _PUNCT.sub(" ", address.strip().upper())).strip()


def _trim(match: dict) -> dict:
    comps = match.get("addressComponents") or {}
    geos = match.get("geographies") or {}
    county = (geos.get("Counties") or [{}])[0].get("NAME")
    coords = match.get("coordinates") or {}
    return {
        "matched_address": match.get("matchedAddress"),
        "lat": coords.get("y"),
        "lon": coords.get("x"),
        "county": county,
        "state": comps.get("state"),
        "zip": comps.get("zip"),
        "city": comps.get("city"),
    }


@tool(profiles=("granular", "all"))
async def geocode_address(address: str) -> dict:
    """Look up the latitude and longitude of a US street address. Returns the
    matched address, coordinates, county and state."""
    if not address or not address.strip():
        return {"error": "address is empty", "hint": "Ask the user for a street address."}

    key = normalize(address)
    cached = await db.geocode_cache_get(key)
    if cached is not None:
        await net.log_cache_hit("census", settings.census_url, {"address": address})
        return {**cached, "match_count": 1, "cached": True}

    try:
        payload = await net.fetch_json(
            service="census",
            url=settings.census_url,
            params={
                "address": address,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "format": "json",
            },
        )
    except net.ReplayMiss as exc:
        return {"error": str(exc),
                "hint": "This address is not in the offline cache. Try one of the seeded demo addresses."}
    except Exception as exc:
        return {"error": f"census geocoder unavailable: {exc}",
                "hint": "Tell the user the geocoding service is unreachable; do not invent coordinates."}

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        return {"error": f"no match for {address!r}", "match_count": 0,
                "hint": "Ask the user for the city, state and ZIP code, then try again."}

    record = _trim(matches[0])
    if record["lat"] is None or record["lon"] is None:
        return {"error": "census returned a match without coordinates",
                "hint": "Ask the user to try a nearby street address."}

    await db.geocode_cache_put(key, record)
    return {**record, "match_count": len(matches), "cached": False}
