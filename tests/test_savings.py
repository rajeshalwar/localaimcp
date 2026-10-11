from mcp_solar.tools.savings import estimate_savings, DEFAULT_COST_PER_WATT, DEFAULT_ITC_RATE


async def test_basic_math():
    r = await estimate_savings(annual_kwh=10_000, rate_per_kwh=0.15, capacity_kw=7.0)
    assert r["annual_savings"] == 1500.0
    gross = 7.0 * 1000 * DEFAULT_COST_PER_WATT
    assert r["system_cost"] == round(gross, 2)
    assert r["federal_credit"] == 0.0
    assert r["net_cost"] == round(gross, 2)
    assert r["simple_payback_years"] == round(gross / 1500.0, 1)


def test_no_federal_credit_by_default():
    """25D ended for systems installed after 2025-12-31."""
    assert DEFAULT_ITC_RATE == 0.0


async def test_explicit_credit_still_applies():
    r = await estimate_savings(annual_kwh=10_000, rate_per_kwh=0.15,
                               system_cost=20_000, itc_rate=0.30)
    assert r["net_cost"] == 14_000.0 and "30% tax credit" in r["assumptions"]


async def test_twenty_year_is_net_of_cost():
    r = await estimate_savings(annual_kwh=10_000, rate_per_kwh=0.15, system_cost=20_000)
    assert r["twenty_year_savings"] == 1500.0 * 20 - 20_000.0


async def test_explicit_cost_beats_capacity_estimate():
    r = await estimate_savings(annual_kwh=1000, capacity_kw=7.0, system_cost=1234.0)
    assert r["system_cost"] == 1234.0


async def test_errors_are_hints_not_exceptions():
    r = await estimate_savings(annual_kwh=0)
    assert "error" in r and "hint" in r
    r = await estimate_savings(annual_kwh=5000)          # no cost, no capacity
    assert "error" in r and "hint" in r


async def test_rate_defaults_are_applied():
    r = await estimate_savings(annual_kwh=1000, capacity_kw=5.0)
    assert r["rate_per_kwh"] > 0


async def test_implausible_inputs_become_hints_not_wrong_answers():
    """Small models guess these; a guessed input must not yield a plausible lie."""
    r = await estimate_savings(annual_kwh=10_000, capacity_kw=7, system_cost=0)
    assert "error" in r and "hint" in r          # observed: produced null payback

    r = await estimate_savings(annual_kwh=10_000, capacity_kw=7, rate_per_kwh=12.5)
    assert "error" in r                           # dollars, not cents

    r = await estimate_savings(annual_kwh=10_000, capacity_kw=7, itc_rate=0.9)
    assert "error" in r


async def test_plausible_inputs_still_pass():
    r = await estimate_savings(annual_kwh=10_000, capacity_kw=7,
                               rate_per_kwh=0.13, itc_rate=0.30, system_cost=21_000)
    assert "error" not in r and r["simple_payback_years"] > 0
