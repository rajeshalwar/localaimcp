"""PostgreSQL access: migrations, caches, egress log, saved assessments."""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Mapping

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings

MIGRATIONS = pathlib.Path(
    os.environ.get("MIGRATIONS_DIR")
    or pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
)

_pool: AsyncConnectionPool | None = None


async def pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(settings.dsn, min_size=1, max_size=8, open=False)
        await _pool.open(wait=True, timeout=30)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def migrate() -> list[str]:
    """Apply every .sql file in order. Files are idempotent (IF NOT EXISTS)."""
    applied = []
    async with (await pool()).connection() as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            await conn.execute(path.read_text())
            applied.append(path.name)
        await conn.commit()
    return applied


# --------------------------------------------------------------------------
# egress log
# --------------------------------------------------------------------------
async def record_egress(
    *, service: str, host: str, path: str, params_sent: Mapping[str, Any],
    status: int | None, cache_hit: bool, duration_ms: int,
) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            """INSERT INTO egress_log
                 (session_id, service, host, path, params_sent, status, cache_hit, duration_ms)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (settings.session_id, service, host, path,
             json.dumps(dict(params_sent)), status, cache_hit, duration_ms),
        )
        await conn.commit()


async def egress_rows(session_id: str | None = None) -> list[dict[str, Any]]:
    sql = """SELECT ts, service, host, path, params_sent, status, cache_hit, duration_ms
             FROM egress_log"""
    args: tuple = ()
    if session_id:
        sql += " WHERE session_id = %s"
        args = (session_id,)
    sql += " ORDER BY ts"
    async with (await pool()).connection() as conn:
        cur = await conn.cursor(row_factory=dict_row).execute(sql, args)
        return await cur.fetchall()


# --------------------------------------------------------------------------
# caches
# --------------------------------------------------------------------------
async def geocode_cache_get(address_norm: str) -> dict[str, Any] | None:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "SELECT response FROM geocode_cache WHERE address_norm = %s", (address_norm,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def geocode_cache_put(address_norm: str, response: Mapping[str, Any], seeded: bool = False) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            """INSERT INTO geocode_cache (address_norm, response, seeded) VALUES (%s,%s,%s)
               ON CONFLICT (address_norm) DO UPDATE SET response = EXCLUDED.response""",
            (address_norm, json.dumps(dict(response)), seeded),
        )
        await conn.commit()


async def pvwatts_cache_get(cache_key: str) -> dict[str, Any] | None:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "SELECT response FROM pvwatts_cache WHERE cache_key = %s", (cache_key,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def pvwatts_cache_put(
    cache_key: str, lat_r: float, lon_r: float,
    params: Mapping[str, Any], response: Mapping[str, Any], seeded: bool = False,
) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            """INSERT INTO pvwatts_cache (cache_key, lat_r, lon_r, params, response, seeded)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response""",
            (cache_key, lat_r, lon_r, json.dumps(dict(params)),
             json.dumps(dict(response)), seeded),
        )
        await conn.commit()


# --------------------------------------------------------------------------
# assessments
# --------------------------------------------------------------------------
async def save_assessment(
    *, address_input: str, matched_address: str | None, lat: float, lon: float,
    county: str | None, inputs: Mapping[str, Any], results: Mapping[str, Any],
    summary: str | None,
) -> int:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            """INSERT INTO assessments
                 (address_input, matched_address, lat, lon, county, inputs, results, summary)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (address_input, matched_address, lat, lon, county,
             json.dumps(dict(inputs)), json.dumps(dict(results)), summary),
        )
        row = await cur.fetchone()
        await conn.commit()
        return int(row[0])


async def list_assessments(limit: int = 10, address_like: str | None = None) -> list[dict[str, Any]]:
    sql = """SELECT id, created_at, address_input, matched_address, lat, lon,
                    county, inputs, results, summary
             FROM assessments"""
    args: tuple = ()
    if address_like:
        sql += " WHERE address_input ILIKE %s OR matched_address ILIKE %s"
        args = (f"%{address_like}%", f"%{address_like}%")
    sql += " ORDER BY created_at DESC LIMIT %s"
    args = args + (limit,)
    async with (await pool()).connection() as conn:
        cur = await conn.cursor(row_factory=dict_row).execute(sql, args)
        rows = await cur.fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["lat"] = float(r["lat"]); r["lon"] = float(r["lon"])
    return rows
