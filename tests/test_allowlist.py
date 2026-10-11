"""Fixtures ship in a public repo: every location in them must be a landmark."""
import json
import pathlib

from scripts import allowlist

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "cache"
ALLOWED = allowlist.load()


def test_census_abbreviations_still_match():
    assert allowlist.is_allowed("100 AUDITORIUM CIR, SAN ANTONIO, TX, 78205", ALLOWED)
    assert allowlist.is_allowed("300 ALAMO PLZ, SAN ANTONIO, TX, 78205", ALLOWED)
    assert allowlist.is_allowed("1717 N HARWOOD ST, DALLAS, TX, 75201", ALLOWED)


def test_house_number_alone_is_not_enough():
    assert not allowlist.is_allowed("1100 ELM ST, AUSTIN, TX, 78701", ALLOWED)


def test_unanchored_coordinates_are_rejected():
    payload = {"geocode": {}, "pvwatts": {"k": {"lat_r": 30.268, "lon_r": -97.724}}}
    assert allowlist.violations(payload, ALLOWED)


def test_committed_fixtures_are_clean():
    for path in FIXTURES.glob("*.json"):
        assert allowlist.violations(json.loads(path.read_text()), ALLOWED) == [], path
