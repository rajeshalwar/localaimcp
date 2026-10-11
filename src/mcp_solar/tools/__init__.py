"""Tool registry with auto-discovery.

Adding a tool must be *one* file: drop a module in this package with an
@tool-decorated function and it is advertised at startup. That promise is only
true because of the pkgutil walk below -- without it, adding a tool would also
mean editing a registration list.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Iterable

ALL_PROFILES = ("granular", "composite", "all")


@dataclass(frozen=True)
class Registered:
    fn: Callable
    profiles: frozenset[str]
    description: str


_REGISTRY: list[Registered] = []


def tool(*, profiles: Iterable[str] = ("granular", "all")) -> Callable:
    """Mark a coroutine as an MCP tool, visible in the given TOOL_PROFILEs."""
    def wrap(fn: Callable) -> Callable:
        _REGISTRY.append(
            Registered(fn=fn, profiles=frozenset(profiles), description=(fn.__doc__ or "").strip())
        )
        return fn
    return wrap


def _discover() -> None:
    for mod in pkgutil.iter_modules(__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")


def register_all(mcp, profile: str = "all") -> list[str]:
    """Attach every tool matching `profile` to the FastMCP instance."""
    _discover()
    names = []
    for entry in _REGISTRY:
        if profile in entry.profiles:
            mcp.tool()(entry.fn)
            names.append(entry.fn.__name__)
    return sorted(names)
