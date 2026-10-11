from mcp_solar.tools.production import cache_key
from mcp_solar.tools.geocode import normalize
from mcp_solar.net import _redact


def test_api_key_never_enters_the_cache_key():
    a = cache_key({"lat": 30.276, "lon": -97.74, "api_key": "SECRET-A"})
    b = cache_key({"lat": 30.276, "lon": -97.74, "api_key": "SECRET-B"})
    assert a == b, "cache key must not depend on the secret"


def test_cache_key_is_stable_and_order_independent():
    assert cache_key({"lat": 1, "lon": 2}) == cache_key({"lon": 2, "lat": 1})


def test_cache_key_changes_with_real_parameters():
    assert cache_key({"lat": 30.276}) != cache_key({"lat": 30.277})


def test_secrets_are_redacted_before_logging():
    out = _redact({"api_key": "SECRET", "lat": 30.2, "token": "T"})
    assert out["api_key"] == "<redacted>"
    assert out["token"] == "<redacted>"
    assert out["lat"] == 30.2


def test_address_normalisation_collapses_whitespace_case_and_punctuation():
    assert normalize("  1100   congress ave,  austin tx ") == "1100 CONGRESS AVE AUSTIN TX"


def test_punctuation_variants_share_a_cache_key():
    """One missing comma must not be a cache miss -- in REPLAY_ONLY that is a
    failed demo."""
    a = normalize("300 Alamo Plaza, San Antonio TX 78205")
    b = normalize("300 Alamo Plaza, San Antonio, TX 78205")
    c = normalize("300 ALAMO PLAZA  SAN ANTONIO TX 78205")
    assert a == b == c
