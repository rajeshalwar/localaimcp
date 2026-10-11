"""One-shot assessment: geocode -> production -> savings -> save.

This exists because a 7B model chaining four tools live, on a projector, over
CPU inference, is a coin flip -- and because collapsing four round trips into
one is the single largest latency win available (plan.md 3.3, 4.1).
"""
from __future__ import annotations

from . import tool
from .geocode import geocode_address
from .production import estimate_solar_production
from .savings import estimate_savings
from .storage import save_assessment


@tool(profiles=("composite", "all"))
async def assess_property(
    address: str,
    system_capacity_kw: float = 7.0,
    rate_per_kwh: float | None = None,
) -> dict:
    """Assess the solar potential of a US property in one call: geocodes the
    address, estimates annual production, computes savings and payback, and
    saves the result. Prefer this over calling the individual tools.

    Only pass system_capacity_kw or rate_per_kwh if the user states them."""
    # Array geometry is deliberately NOT exposed here. Observed in testing: a
    # 3B model happily invented `azimuth=235` and `losses=0.02` -- plausible
    # shapes, no basis in anything the user said, and they silently move the
    # answer. Orientation defaults to due south with tilt = latitude, which is
    # the standard rule of thumb. Use estimate_solar_production directly when
    # the geometry genuinely matters.
    tilt: float | None = None
    azimuth: float = 180.0
    located = await geocode_address(address)
    if "error" in located:
        return {"stage": "geocode", **located}

    production = await estimate_solar_production(
        lat=located["lat"], lon=located["lon"],
        system_capacity_kw=system_capacity_kw, tilt=tilt, azimuth=azimuth,
    )
    if "error" in production:
        return {"stage": "production", "location": located, **production}

    money = await estimate_savings(
        annual_kwh=production["ac_annual_kwh"],
        rate_per_kwh=rate_per_kwh,
        capacity_kw=system_capacity_kw,
    )
    if "error" in money:
        return {"stage": "savings", "location": located, "production": production, **money}

    saved = await save_assessment(
        address=address, lat=located["lat"], lon=located["lon"],
        matched_address=located.get("matched_address") or "",
        county=located.get("county") or "",
        inputs={"system_capacity_kw": system_capacity_kw, "tilt": tilt,
                "azimuth": azimuth, "rate_per_kwh": money["rate_per_kwh"]},
        results={"production": production, "savings": money},
    )

    return {
        "location": located,
        "production": production,
        "savings": money,
        "assessment_id": saved.get("id"),
    }
