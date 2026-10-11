"""The public-landmark allowlist, shared by export_fixtures and the pre-commit hook.

Fixtures ship in a public repo, so every location in them must trace back to an
address in fixtures/seed_addresses.txt:

  * a geocode entry must match an allowlisted HOUSE NUMBER *and* STREET NAME
    (the number alone let any "1100 <anything>" through);
  * a PVWatts entry must sit at the rounded coordinates of an allowlisted
    geocode entry -- a coordinate is a location too, even without an address.

Standalone on purpose: runnable as `python3 scripts/allowlist.py FILE...` from a
git hook with no dependencies and no database.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ALLOWLIST = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "seed_addresses.txt"
COORD_PRECISION = 3
_DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}


def _tokens(address: str) -> list[str]:
    return re.sub(r"[^A-Z0-9 ]", " ", (address or "").upper()).split()


def street_key(address: str) -> tuple[str, str] | None:
    """(house number, first non-directional street word), e.g. ('1717', 'HARWOOD').

    Suffixes are deliberately ignored -- the Census geocoder rewrites
    "Circle" as "CIR" and "Plaza" as "PLZ".
    """
    toks = _tokens(address)
    if len(toks) < 2 or not toks[0].isdigit():
        return None
    street = next((t for t in toks[1:] if t not in _DIRECTIONALS), None)
    return (toks[0], street) if street else None


def load(path: pathlib.Path = ALLOWLIST) -> set[tuple[str, str]]:
    keys = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and (k := street_key(line)):
            keys.add(k)
    return keys


def is_allowed(address: str, allowed: set[tuple[str, str]]) -> bool:
    return street_key(address) in allowed


def rounded(lat, lon) -> tuple[float, float]:
    return round(float(lat), COORD_PRECISION), round(float(lon), COORD_PRECISION)


def violations(payload: dict, allowed: set[tuple[str, str]]) -> list[str]:
    """Everything in a fixture payload that is not traceable to the allowlist."""
    bad = []
    coords = set()
    for key, rec in (payload.get("geocode") or {}).items():
        matched = rec.get("matched_address") or ""
        if not (is_allowed(matched, allowed) and is_allowed(key, allowed)):
            bad.append(f"geocode: {matched or key}")
        elif rec.get("lat") is not None and rec.get("lon") is not None:
            coords.add(rounded(rec["lat"], rec["lon"]))
    for key, entry in (payload.get("pvwatts") or {}).items():
        if rounded(entry["lat_r"], entry["lon_r"]) not in coords:
            bad.append(f"pvwatts: ({entry['lat_r']}, {entry['lon_r']}) is not an allowlisted address")
    return bad


def main(argv: list[str]) -> int:
    allowed = load()
    fail = 0
    for f in argv:
        for v in violations(json.loads(pathlib.Path(f).read_text()), allowed):
            print(f"{f}: not on the public-landmark allowlist -> {v}")
            fail = 1
    return fail


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
