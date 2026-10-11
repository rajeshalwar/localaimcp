"""Savings arithmetic. Pure, local, and deliberately not done by the model."""
from __future__ import annotations

from . import tool
from ..config import settings

# Rough installed cost per watt for residential solar in Texas, before credits.
DEFAULT_COST_PER_WATT = 2.80

# The residential clean energy credit (IRC 25D) ended for systems installed after
# 2025-12-31 (P.L. 119-21, the 2025 reconciliation act). A homeowner buying a
# system today gets no federal credit, so the default is zero. The parameter
# stays for historical comparisons or a user who states a different incentive.
DEFAULT_ITC_RATE = 0.0


@tool(profiles=("granular", "composite", "all"))
async def estimate_savings(
    annual_kwh: float,
    rate_per_kwh: float | None = None,
    system_cost: float | None = None,
    capacity_kw: float | None = None,
    itc_rate: float = DEFAULT_ITC_RATE,
) -> dict:
    """Turn annual solar production into dollars: savings, net cost after any
    tax credit, and simple payback. Runs entirely offline -- no network."""
    if annual_kwh is None or annual_kwh <= 0:
        return {"error": "annual_kwh must be a positive number",
                "hint": "Call estimate_solar_production first and pass its ac_annual_kwh."}

    # Small models guess these rather than omitting them, and a guessed input
    # yields a confidently wrong answer. Observed in testing: system_cost=0
    # (payback became null), itc_rate=0.22, rate_per_kwh=0.125. Reject the
    # implausible ones so the model gets a hint instead of a plausible lie.
    if rate_per_kwh is not None and not (0.01 <= float(rate_per_kwh) <= 1.0):
        return {"error": f"rate_per_kwh={rate_per_kwh} is not a plausible US retail rate",
                "hint": "Omit rate_per_kwh entirely unless the user stated a rate; "
                        "the tool has a sensible default."}
    if system_cost is not None and float(system_cost) <= 0:
        return {"error": f"system_cost={system_cost} is not a valid cost",
                "hint": "Omit system_cost and pass capacity_kw instead; the tool "
                        "estimates installed cost itself."}
    if not (0.0 <= float(itc_rate) <= 0.5):
        return {"error": f"itc_rate={itc_rate} is outside the plausible range",
                "hint": "Omit itc_rate unless the user stated one; the residential "
                        "federal credit ended for systems installed after 2025."}

    rate = float(rate_per_kwh if rate_per_kwh is not None else settings.default_rate_per_kwh)

    cost_given = system_cost is not None
    if system_cost is None:
        if capacity_kw is None:
            return {"error": "need either system_cost or capacity_kw",
                    "hint": "Pass capacity_kw (the system size in kW) and I will estimate cost."}
        system_cost = float(capacity_kw) * 1000.0 * DEFAULT_COST_PER_WATT

    credit = system_cost * itc_rate
    net_cost = system_cost - credit
    annual_savings = float(annual_kwh) * rate
    payback = (net_cost / annual_savings) if annual_savings > 0 else None

    return {
        "annual_savings": round(annual_savings, 2),
        "rate_per_kwh": round(rate, 4),
        "system_cost": round(system_cost, 2),
        "federal_credit": round(credit, 2),
        "net_cost": round(net_cost, 2),
        "simple_payback_years": round(payback, 1) if payback else None,
        "twenty_year_savings": round(annual_savings * 20 - net_cost, 2),
        "assumptions": (
            f"Flat ${rate:.3f}/kWh, "
            + (f"${system_cost:,.0f} system cost as given, " if cost_given else
               f"${DEFAULT_COST_PER_WATT:.2f}/W installed, ")
            + (f"{round(itc_rate * 100)}% tax credit. " if itc_rate else
               "no federal tax credit (the residential credit ended after 2025). ")
            + "Ignores rate inflation, "
            "panel degradation (~0.5%/yr) and time-of-use pricing."
        ),
    }
