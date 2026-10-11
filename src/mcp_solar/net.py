"""THE egress chokepoint.

Every byte that leaves this machine goes through this module. Nothing else in
the tree may import httpx -- tests/test_chokepoint.py enforces that by grep.

Three jobs:
  1. Make the request.
  2. Record exactly what was transmitted, in egress_log.
  3. Refuse to make any request at all when REPLAY_ONLY is set.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Mapping

import httpx

from .config import settings
from . import db

log = logging.getLogger(__name__)

# Never let these reach egress_log; the log is dumpable and the repo is public.
_ALWAYS_REDACT = {"api_key", "key", "token", "password"}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            headers={"User-Agent": "localaimcp/0.1"},
            # A redirect would send the same parameters to a host the egress
            # log never names. Fail instead; the log stays the whole truth.
            follow_redirects=False,
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class ReplayMiss(RuntimeError):
    """Raised when REPLAY_ONLY is set and the answer is not already cached."""


def _redact(params: Mapping[str, Any], extra: Iterable[str] = ()) -> dict[str, Any]:
    drop = _ALWAYS_REDACT | set(extra)
    return {k: ("<redacted>" if k in drop else v) for k, v in params.items()}


async def log_cache_hit(service: str, url: str, params: Mapping[str, Any]) -> None:
    """Record that a question was answered without leaving the machine."""
    host, _, path = url.partition("://")[2].partition("/")
    await db.record_egress(
        service=service, host=host, path="/" + path,
        params_sent=_redact(params), status=None, cache_hit=True, duration_ms=0,
    )


async def fetch_json(
    *,
    service: str,
    url: str,
    params: Mapping[str, Any],
    redact: Iterable[str] = (),
) -> dict[str, Any]:
    """Perform the only kind of outbound request this program makes."""
    host, _, path = url.partition("://")[2].partition("/")
    path = "/" + path

    if settings.replay_only:
        # The point of replay mode: fail loudly rather than quietly reach out.
        raise ReplayMiss(
            f"REPLAY_ONLY is set and {service} has no cached answer for these "
            f"parameters. Seed it with `make seed-cache` or unset REPLAY_ONLY."
        )

    started = time.perf_counter()
    status: int | None = None
    try:
        resp = await _get_client().get(url, params=dict(params))
        status = resp.status_code
        resp.raise_for_status()
        return resp.json()
    finally:
        # A failed log write must not mask the request's own outcome -- but it
        # must be loud, because an unlogged request breaks the egress claim.
        try:
            await db.record_egress(
                service=service, host=host, path=path,
                params_sent=_redact(params, redact), status=status, cache_hit=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            log.exception("EGRESS NOT LOGGED: %s %s%s", service, host, path)
