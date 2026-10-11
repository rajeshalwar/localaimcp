"""S7 gate: is a demo turn fast enough to do live?

Runs the same question N times against the running stack and reports the
distribution. Run it on the machine you will actually present from -- the
answer is entirely hardware-dependent, and it decides MODEL_NAME.

    podman compose run --rm --entrypoint python3 agent /app/scripts/bench.py
    MODEL_NAME=qwen2.5:3b-instruct ... /app/scripts/bench.py --runs 5
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import statistics
import sys
import time

import httpx
from mcp import Client

sys.path.insert(0, "/app/src")

from agent import ollama                      # noqa: E402
from agent.main import SYSTEM_PROMPT, run_turn  # noqa: E402
from agent.schema_bridge import build           # noqa: E402

QUESTION = ("Assess solar for 1100 Congress Ave, Austin TX 78701 "
            "with a 7 kW system.")

# plan.md S7
TARGET_MEDIAN = 45.0
TARGET_P90 = 90.0


class Quiet:
    """run_turn prints a trace; swallow it so the timings stay readable."""
    def write(self, *_a, **_k): pass
    def flush(self): pass


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--mcp-url", default=os.environ.get("MCP_URL", "http://appliance:8000/mcp"))
    ap.add_argument("--question", default=QUESTION)
    args = ap.parse_args()

    print(f"model   : {ollama.MODEL}")
    print(f"ctx     : {ollama.NUM_CTX}   keep_alive: {ollama.KEEP_ALIVE}")
    print(f"question: {args.question!r}")
    print(f"runs    : {args.runs}\n")

    times: list[float] = []
    calls: list[int] = []

    async with httpx.AsyncClient() as http:
        ok, detail = await ollama.ensure_model(http)
        if not ok:
            print("FAIL:", detail)
            return 2

        print("warming…", end="", flush=True)
        t0 = time.perf_counter()
        await ollama.warm(http)
        print(f" {time.perf_counter() - t0:.1f}s\n")

        async with Client(args.mcp_url) as mcp:
            schemas = build((await mcp.list_tools()).tools)
            print(f"{len(schemas)} tools advertised\n")

            for i in range(1, args.runs + 1):
                messages = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": args.question}]
                trace: list = []
                real, sys.stdout = sys.stdout, Quiet()
                t0 = time.perf_counter()
                try:
                    await run_turn(mcp, http, messages, schemas, trace)
                finally:
                    sys.stdout = real
                elapsed = time.perf_counter() - t0
                times.append(elapsed)
                calls.append(len(trace))
                print(f"  run {i}: {elapsed:6.1f}s  {len(trace)} tool call(s)")

    times.sort()
    median = statistics.median(times)
    # Nearest-rank p90. The old int(n*0.9)-1 was the 4th of 5 runs -- a p80.
    p90 = times[max(0, math.ceil(len(times) * 0.9) - 1)]
    print(f"\n  min {times[0]:.1f}s   median {median:.1f}s   p90 {p90:.1f}s   max {times[-1]:.1f}s")
    print(f"  tool calls per turn: {min(calls)}–{max(calls)}")

    ok_median, ok_p90 = median <= TARGET_MEDIAN, p90 <= TARGET_P90
    print(f"\n  S7 median <= {TARGET_MEDIAN:.0f}s : {'PASS' if ok_median else 'FAIL'}")
    print(f"  S7 p90    <= {TARGET_P90:.0f}s : {'PASS' if ok_p90 else 'FAIL'}")
    if not (ok_median and ok_p90):
        print("\n  Try a smaller model (MODEL_NAME=qwen2.5:3b-instruct) or give the")
        print("  podman VM more CPUs. Do not take a failing model on stage.")
    return 0 if (ok_median and ok_p90) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
