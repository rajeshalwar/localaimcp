"""PVWatts v8 response parsing.

developer.nrel.gov was unreachable from the environment this code was written
in, so the live call is verified separately by `make check-nrel`. This pins the
parsing against the documented v8 response shape so a field rename or a units
change fails here rather than on stage.
"""
import dataclasses

import pytest

from mcp_solar.tools import production


def _with_key(key):
    """settings is a frozen dataclass; build a copy rather than mutate it."""
    return dataclasses.replace(production.settings, nrel_api_key=key)

# Trimmed real-shape PVWatts v8 payload (monthly timeframe).
PAYLOAD = {
    "inputs": {"lat": "30.276", "lon": "-97.74", "system_capacity": "7"},
    "errors": [], "warnings": [], "version": "8.3.1",
    "station_info": {"lat": 30.27, "lon": -97.74, "location": "Austin",
                     "city": "AUSTIN", "state": "TX", "distance": 1832},
    "outputs": {
        "ac_monthly": [742.1, 782.4, 998.2, 1021.7, 1043.9, 1039.5,
                       1072.3, 1061.8, 951.6, 917.4, 763.2, 700.9],
        "solrad_monthly": [3.9, 4.3, 5.2, 5.4, 5.4, 5.6, 5.8, 5.7, 5.1, 4.9, 4.1, 3.7],
        "dc_monthly": [770.0] * 12,
        "poa_monthly": [120.0] * 12,
        "ac_annual": 11095.0, "solrad_annual": 4.93, "capacity_factor": 18.1,
    },
}


@pytest.fixture
def no_network(monkeypatch):
    async def fake_fetch(**kwargs):
        fake_fetch.sent = kwargs["params"]
        return PAYLOAD
    async def no_cache(_key): return None
    async def put(*a, **k): return None
    monkeypatch.setattr(production.net, "fetch_json", fake_fetch)
    monkeypatch.setattr(production.db, "pvwatts_cache_get", no_cache)
    monkeypatch.setattr(production.db, "pvwatts_cache_put", put)
    monkeypatch.setattr(production, "settings", _with_key("test-key"))
    return fake_fetch


async def test_parses_the_documented_shape(no_network):
    out = await production.estimate_solar_production(lat=30.2764447, lon=-97.7397521)
    assert out["ac_annual_kwh"] == 11095.0
    assert len(out["ac_monthly_kwh"]) == 12
    assert out["capacity_factor"] == 18.1
    assert out["solrad_annual"] == 4.93
    assert out["weather_station"] == "Austin"


async def test_coordinates_are_rounded_before_transmission(no_network):
    """P3: NREL must never receive a precise location."""
    await production.estimate_solar_production(lat=30.2764447016, lon=-97.7397520956)
    sent = no_network.sent
    assert sent["lat"] == 30.276 and sent["lon"] == -97.74
    assert len(str(sent["lat"]).split(".")[1]) <= 3


async def test_tilt_defaults_to_latitude(no_network):
    # Rule of thumb: tilt = site latitude, rounded to 2dp (degrees finer than
    # that are meaningless, and it is coarser than the transmitted coordinate).
    await production.estimate_solar_production(lat=30.2764447, lon=-97.7397521)
    assert no_network.sent["tilt"] == 30.28


async def test_explicit_tilt_wins(no_network):
    await production.estimate_solar_production(lat=30.2764447, lon=-97.74, tilt=15)
    assert no_network.sent["tilt"] == 15.0


async def test_api_errors_become_hints(monkeypatch):
    async def fetch_err(**kwargs):
        return {"errors": ["system_capacity must be between 0.05 and 500000"], "outputs": {}}
    monkeypatch.setattr(production.net, "fetch_json", fetch_err)
    monkeypatch.setattr(production.db, "pvwatts_cache_get", lambda _k: _none())
    monkeypatch.setattr(production, "settings", _with_key("test-key"))
    out = await production.estimate_solar_production(lat=30.0, lon=-97.0)
    assert "error" in out and "hint" in out


async def _none(): return None


async def test_missing_key_is_a_hint_not_a_crash(monkeypatch):
    monkeypatch.setattr(production.db, "pvwatts_cache_get", lambda _k: _none())
    monkeypatch.setattr(production, "settings", _with_key(""))
    out = await production.estimate_solar_production(lat=30.0, lon=-97.0)
    assert "NREL_API_KEY" in out["error"]
