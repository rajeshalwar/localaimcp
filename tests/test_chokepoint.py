"""P2: net.py is the only module allowed to make outbound requests."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
ALLOWED = {"net.py"}
_CLIENTS = r"(?:httpx|requests|urllib3|aiohttp|urllib\.request|urllib|http\.client|http|socket|ssl)"
PATTERN = re.compile(rf"^\s*(?:import\s+{_CLIENTS}\b|from\s+{_CLIENTS}\b)", re.M)


def test_only_net_py_imports_an_http_client():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name in ALLOWED:
            continue
        # The agent is a separate program with its own, separate egress story.
        if "agent" in path.parts:
            continue
        if PATTERN.search(path.read_text()):
            offenders.append(str(path.relative_to(SRC)))
    assert not offenders, f"these modules bypass the egress chokepoint: {offenders}"


def test_pattern_catches_stdlib_clients():
    for line in ("import socket", "import urllib.request", "from urllib import request",
                 "from http.client import HTTPSConnection", "import http.client"):
        assert PATTERN.search(line), line
    assert not PATTERN.search("import httpxlike")
