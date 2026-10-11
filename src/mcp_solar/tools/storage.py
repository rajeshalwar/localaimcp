"""Persisting and recalling assessments. Local Postgres, never leaves the box."""
from __future__ import annotations

from . import tool
from .. import db


@tool(profiles=("granular", "composite", "all"))
async def save_assessment(
    address: str,
    lat: float,
    lon: float,
    inputs: dict,
    results: dict,
    summary: str = "",
    matched_address: str = "",
    county: str = "",
) -> dict:
    """Save a completed solar assessment to the local database so it can be
    recalled or compared later."""
    try:
        new_id = await db.save_assessment(
            address_input=address, matched_address=matched_address or None,
            lat=float(lat), lon=float(lon), county=county or None,
            inputs=inputs or {}, results=results or {}, summary=summary or None,
        )
    except Exception as exc:
        return {"error": f"could not save: {exc}",
                "hint": "Report the answer to the user anyway; saving is not essential."}
    return {"id": new_id, "saved": True}


@tool(profiles=("granular", "composite", "all"))
async def list_assessments(limit: int = 10, address_like: str = "") -> dict:
    """List previously saved solar assessments, most recent first. Optionally
    filter by a fragment of the address."""
    try:
        rows = await db.list_assessments(limit=int(limit), address_like=address_like or None)
    except Exception as exc:
        return {"error": f"could not read assessments: {exc}", "hint": "Tell the user storage is unavailable."}
    return {"count": len(rows), "assessments": rows}
