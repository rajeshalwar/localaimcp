"""Drop tool arguments the model made up.

Rule 6 of the system prompt says: do not pass a rate, cost, tax credit or array
geometry unless the user stated it. Models break it anyway. Observed end to end
on qwen2.5:7b: `system_cost=28000, itc_rate=0.26, rate_per_kwh=0.12` for a
question that mentioned none of them. Every value was in range, so the tool
accepted them and the answer confidently quoted a tax credit that does not
exist. A prompt is a request; this is enforcement.

The test is deliberately dumb: a guarded argument survives only if its value
appears as a number in something the user typed (as-is, as a percentage or
cents, or with a "k" suffix). Otherwise it is removed and the tool's own
default applies -- and the trace says so, out loud.
"""
from __future__ import annotations

import re

GUARDED = frozenset({"rate_per_kwh", "system_cost", "itc_rate", "tilt", "azimuth", "losses"})

_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)


def stated_numbers(messages: list[dict]) -> set[float]:
    """Every value a number in the user's messages could plausibly mean."""
    found: set[float] = set()
    for m in messages:
        if m.get("role") != "user":
            continue
        for digits, k in _NUMBER.findall(m.get("content") or ""):
            try:
                n = float(digits.replace(",", ""))
            except ValueError:
                continue
            n = n * 1000 if k else n
            found |= {n, n / 100}            # 12 cents -> 0.12, 30% -> 0.30
    return found


def _was_stated(value, stated: set[float]) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return any(abs(v - s) <= 1e-6 * max(1.0, abs(s)) for s in stated)


def strip_unstated(args: dict, messages: list[dict]) -> tuple[dict, dict]:
    """Return (kept args, dropped args)."""
    stated = stated_numbers(messages)
    kept, dropped = {}, {}
    for k, v in args.items():
        if k in GUARDED and v is not None and not _was_stated(v, stated):
            dropped[k] = v
        else:
            kept[k] = v
    return kept, dropped
