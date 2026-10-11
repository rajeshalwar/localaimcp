"""The agent host: an Ollama tool-calling loop wired to an MCP server.

Deliberately small and deliberately loud -- every tool call is printed, because
watching the model decide is the whole point.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx
from mcp import Client

from . import guard, ollama, trace
from .schema_bridge import build as build_schemas

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")
MAX_ITERATIONS = 6

# Observed failure modes this prompt exists to prevent, all seen in testing:
#   - a 3B model answering with hand-rolled physics and zero tool calls
#   - a 7B model geocoding, then passing DIFFERENT coordinates to PVWatts
#   - both models computing savings themselves from an invented $/kWh rate
# Hence the imperative, numbered form: small models follow rules far better
# than they follow prose.
SYSTEM_PROMPT = (
    "You are a local solar assessment assistant running on the user's own hardware.\n"
    "\n"
    "RULES -- follow all of them, every time:\n"
    "1. You have NO knowledge of any address, coordinate, solar figure or price. "
    "The ONLY way to learn one is to call a tool.\n"
    "2. NEVER do arithmetic yourself. Not production, not savings, not payback, "
    "not monthly averages. Call the tool that computes it.\n"
    "3. NEVER invent a latitude or longitude. Call geocode_address, then copy its "
    "lat and lon into the next call EXACTLY, digit for digit.\n"
    "4. Quote numbers from tool results exactly as returned. Do not round, "
    "rescale, or recompute them.\n"
    "5. If a tool returns an error, read its hint and say plainly that you could "
    "not get the data. Never fill the gap with an estimate.\n"
    "6. Do NOT pass rate_per_kwh, system_cost, itc_rate, tilt, azimuth or losses "
    "unless the user stated that number themselves. Omit them and let the tool "
    "use its own defaults -- a guessed input produces a confidently wrong answer.\n"
    "\n"
    "Once you have the data, explain it to a homeowner in plain English: annual "
    "production, what it is worth per year, and the payback period. State the "
    "assumptions the tools reported. Be concise."
)


def _tool_result_text(result) -> str:
    parts = [getattr(b, "text", "") for b in getattr(result, "content", []) or []]
    return "\n".join(p for p in parts if p) or "{}"


def _compact(messages: list[dict], start: int) -> None:
    """Keep only the question and the final answer from a finished turn.

    Tool results (twelve monthly figures, the full location record...) are
    most of a turn's tokens. Left in, a handful of REPL turns overflows
    OLLAMA_NUM_CTX and Ollama silently drops the start of the prompt -- which
    is the system prompt and its rules. The narrated answer keeps enough
    context for a follow-up question.
    """
    turn = messages[start:]
    if len(turn) > 2:
        messages[start:] = [turn[0], turn[-1]]


async def run_turn(mcp: Client, http: httpx.AsyncClient, messages: list[dict],
                   schemas: list[dict], json_trace: list | None) -> None:
    started = time.perf_counter()
    calls_made = 0
    final_text = ""

    for _ in range(MAX_ITERATIONS):
        reply = await ollama.chat(http, messages, schemas)
        msg = reply.get("message") or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            # This turn IS the answer. Do not append it and then ask the model
            # to continue -- that yields an empty completion and pays for a
            # second full generation (~20s on CPU) to produce nothing.
            final_text = msg.get("content", "") or ""
            break

        messages.append(msg)
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            args, dropped = guard.strip_unstated(args, messages)
            trace.call(name, args)
            if dropped:
                trace.warn("dropped, not stated by the user: "
                           + ", ".join(f"{k}={v}" for k, v in dropped.items())
                           + " -> tool defaults apply")
            t0 = time.perf_counter()
            try:
                result = await mcp.call_tool(name, args)
                text = _tool_result_text(result)
            except Exception as exc:
                text = json.dumps({"error": str(exc), "hint": "Tell the user the tool failed."})
            ms = int((time.perf_counter() - t0) * 1000)

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            trace.result(name, parsed, ms)
            calls_made += 1
            if json_trace is not None:
                json_trace.append({"tool": name, "args": args, "result": parsed, "ms": ms})

            messages.append({"role": "tool", "content": text})
    else:
        trace.warn(f"stopped after {MAX_ITERATIONS} tool iterations without a final answer")

    # The closing narration. If the loop already produced it, print it: a
    # second streaming pass would regenerate the same answer and double the
    # wall time. We only stream when the loop ended without an answer.
    print()
    if not final_text:
        chunks: list[str] = []
        async for piece in ollama.stream_final(http, messages):
            chunks.append(piece)
            print(piece, end="", flush=True)
        final_text = "".join(chunks)
    else:
        print(final_text, end="")
    print("\n")
    messages.append({"role": "assistant", "content": final_text})
    trace.turn_summary(calls_made, time.perf_counter() - started)


async def amain(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="solar-agent")
    ap.add_argument("question", nargs="*", help="ask once and exit; omit for a REPL")
    ap.add_argument("--mcp-url", default=MCP_URL)
    ap.add_argument("--json-trace", metavar="PATH", help="write the full transcript here")
    ap.add_argument("--no-warm", action="store_true", help="skip the model warm-up")
    args = ap.parse_args(argv)

    json_trace: list | None = [] if args.json_trace else None

    async with httpx.AsyncClient() as http:
        ok, detail = await ollama.ensure_model(http)
        if not ok:
            print(f"error: {detail}", file=sys.stderr)
            return 2
        trace.note(f"model {detail} @ {ollama.HOST}  (ctx {ollama.NUM_CTX}, keep_alive {ollama.KEEP_ALIVE})")

        if not args.no_warm:
            trace.note("warming the model so the first question is not a cold load…")
            t0 = time.perf_counter()
            await ollama.warm(http)
            trace.note(f"warm in {time.perf_counter() - t0:.1f}s")

        async with Client(args.mcp_url) as mcp:
            listed = await mcp.list_tools()
            schemas = build_schemas(listed.tools)
            trace.note(f"{len(schemas)} tools from {args.mcp_url}: "
                       + ", ".join(s['function']['name'] for s in schemas))

            messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

            if args.question:
                messages.append({"role": "user", "content": " ".join(args.question)})
                await run_turn(mcp, http, messages, schemas, json_trace)
            else:
                print("\nAsk about a property, or Ctrl-D to quit.\n")
                while True:
                    try:
                        line = input("you › ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break
                    if not line:
                        continue
                    if line in {"/quit", "/exit"}:
                        break
                    start = len(messages)
                    messages.append({"role": "user", "content": line})
                    await run_turn(mcp, http, messages, schemas, json_trace)
                    _compact(messages, start)

    if args.json_trace and json_trace is not None:
        with open(args.json_trace, "w") as fh:
            json.dump(json_trace, fh, indent=2, default=str)
        trace.note(f"trace written to {args.json_trace}")
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
