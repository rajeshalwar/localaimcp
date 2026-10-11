"""MCP tool schemas -> Ollama's OpenAI-style function schemas.

Two things here are not obvious, and both cost real debugging time:

1. In the mcp 2.x Python SDK the attribute is `input_schema`; `inputSchema` is
   only the wire alias. Reading the wrong one silently yields an EMPTY schema,
   so the model is handed a tool with no parameters and quietly misuses it.

2. An optional Python parameter (`tilt: float | None = None`) becomes
   `{"anyOf": [{"type": "number"}, {"type": "null"}]}`. Ollama's tool parser
   rejects `anyOf` with a 400. We flatten it to the non-null branch.
"""
from __future__ import annotations

from typing import Any

_NOISE = ("title", "$schema", "additionalProperties")


def _flatten(node: Any) -> Any:
    """Make a JSON Schema fragment palatable to Ollama."""
    if isinstance(node, list):
        return [_flatten(n) for n in node]
    if not isinstance(node, dict):
        return node

    node = {k: v for k, v in node.items() if k not in _NOISE}

    # anyOf/oneOf with a null branch is just "optional" -- collapse it.
    for key in ("anyOf", "oneOf"):
        if key in node:
            branches = [b for b in node[key] if b.get("type") != "null"]
            chosen = _flatten(branches[0]) if branches else {"type": "string"}
            merged = {k: v for k, v in node.items() if k != key}
            merged.update(chosen)
            node = merged
            break

    for key in ("properties", "$defs", "definitions"):
        if isinstance(node.get(key), dict):
            node[key] = {k: _flatten(v) for k, v in node[key].items()}
    if "items" in node:
        node["items"] = _flatten(node["items"])
    return node


def get_input_schema(tool: Any) -> dict:
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    if not schema:
        return {"type": "object", "properties": {}}
    return _flatten(dict(schema))


def mcp_tool_to_ollama(tool: Any) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (getattr(tool, "description", "") or "").strip(),
            "parameters": get_input_schema(tool),
        },
    }


def build(tools: list[Any]) -> list[dict]:
    """Stable ordering matters: the tool list is part of the prompt prefix, and
    a stable prefix is what lets Ollama reuse its KV cache between turns."""
    return [mcp_tool_to_ollama(t) for t in sorted(tools, key=lambda t: t.name)]
