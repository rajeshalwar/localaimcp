"""Trace output. This is the demo, not debug noise -- the audience watching the
agent decide is the payoff, so it gets to be readable."""
from __future__ import annotations

import json
import os
import sys

_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
DIM, CYAN, GREEN, YELLOW, RED, RESET = (
    ("\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m") if _TTY
    else ("", "", "", "", "", "")
)


def _short(value, limit: int = 160) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def call(name: str, args: dict) -> None:
    inner = ", ".join(f"{k}={_short(v, 60)}" for k, v in args.items())
    print(f"{CYAN}  → {name}({inner}){RESET}", flush=True)


def result(name: str, payload, ms: int) -> None:
    is_err = isinstance(payload, dict) and "error" in payload
    colour = RED if is_err else DIM
    print(f"{colour}  ← {name} {_short(payload)} {DIM}[{ms} ms]{RESET}", flush=True)


def note(msg: str) -> None:
    print(f"{DIM}  · {msg}{RESET}", flush=True)


def warn(msg: str) -> None:
    print(f"{YELLOW}  ! {msg}{RESET}", flush=True)


def turn_summary(tool_calls: int, elapsed_s: float) -> None:
    print(f"{DIM}  · turn complete: {tool_calls} tool call(s), {elapsed_s:.1f}s{RESET}", flush=True)
