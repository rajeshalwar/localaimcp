"""Print every outbound request this session made. The talk's closing evidence."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp_solar import db
from mcp_solar.config import settings


async def report(session: str | None, reset: bool) -> int:
    if reset:
        async with (await db.pool()).connection() as conn:
            await conn.execute("TRUNCATE egress_log")
            await conn.commit()
        print("egress_log cleared.")
        await db.close()
        return 0

    # This script runs as its OWN process, so settings.session_id is a fresh
    # random id that never appears in the table. Defaulting to it printed "no
    # requests" after a perfectly good demo. Default to the newest session
    # actually present instead.
    if session is None:
        async with (await db.pool()).connection() as conn:
            cur = await conn.execute(
                "SELECT session_id FROM egress_log ORDER BY ts DESC LIMIT 1")
            row = await cur.fetchone()
            session = row[0] if row else None

    rows = await db.egress_rows(session)
    if not rows:
        print(f"No outbound requests recorded{' for session ' + session if session else ''}.")
        await db.close()
        return 0

    live = [r for r in rows if not r["cache_hit"]]
    cached = len(rows) - len(live)

    print(f"\n{'WHEN':<10} {'SERVICE':<8} {'HOST':<32} {'STATUS':<7} {'MS':>6}  WHAT WAS SENT")
    print("-" * 118)
    for r in rows:
        when = r["ts"].strftime("%H:%M:%S")
        status = "CACHED" if r["cache_hit"] else str(r["status"] or "-")
        sent = json.dumps(r["params_sent"], sort_keys=True)
        print(f"{when:<10} {r['service']:<8} {r['host']:<32} {status:<7} {r['duration_ms']:>6}  {sent[:60]}")
    print("-" * 118)
    print(f"\n  {len(live)} request(s) actually left this machine.")
    print(f"  {cached} question(s) were answered from the local cache.\n")
    print("  Nothing else was transmitted: no prompt, no conversation, no")
    print("  reasoning, no stored result. The model has no route to the network.\n")
    await db.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="egress-report")
    ap.add_argument("--session", default=os.environ.get("SESSION_ID") or None,
                    help="limit to one demo run (default: the most recent)")
    ap.add_argument("--all", action="store_true", help="every session ever")
    ap.add_argument("--reset", action="store_true", help="truncate the log")
    args = ap.parse_args()
    return asyncio.run(report(None if args.all else args.session, args.reset))


if __name__ == "__main__":
    sys.exit(main())
