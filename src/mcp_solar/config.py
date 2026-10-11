"""Configuration, read once from the environment.

Deliberately plain: a projector-readable dataclass beats settings-framework
magic when the whole point of the talk is that you can read the code.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- outbound APIs -------------------------------------------------
    nrel_api_key: str = field(default_factory=lambda: os.environ.get("NREL_API_KEY", ""))
    # `geographies` rather than `locations`: only it returns the county.
    census_url: str = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
    # NLR (formerly NREL) moved the developer network to developer.nlr.gov.
    # v8 is still the current API version; it is v6 that is being deprecated.
    pvwatts_url: str = "https://developer.nlr.gov/api/pvwatts/v8.json"

    # --- privacy -------------------------------------------------------
    # REPLAY_ONLY turns every cache miss into an error instead of a request.
    # This is what lets the demo run with the network physically off.
    replay_only: bool = field(default_factory=lambda: _bool("REPLAY_ONLY"))
    # Coordinates are rounded before they are ever transmitted (P3).
    coord_precision: int = 3

    # --- database ------------------------------------------------------
    pg_host: str = field(default_factory=lambda: os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    pg_db: str = field(default_factory=lambda: os.environ.get("POSTGRES_DB", "solar"))
    pg_user: str = field(default_factory=lambda: os.environ.get("POSTGRES_USER", "solar"))
    pg_password: str = field(default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", "localdev"))

    # --- behaviour -----------------------------------------------------
    # Which tools get advertised. The composite tool is strictly cheaper for a
    # small model, so with "all" it will win essentially every time -- hence a
    # switch, so the talk can show the granular chain first (plan.md 4.1).
    tool_profile: str = field(default_factory=lambda: os.environ.get("TOOL_PROFILE", "all").lower())
    default_rate_per_kwh: float = field(
        default_factory=lambda: float(os.environ.get("DEFAULT_RATE_PER_KWH", "0.15"))
    )
    # Scopes the egress report to one demo run so the table does not accumulate
    # every rehearsal into the number quoted on stage.
    session_id: str = field(
        default_factory=lambda: os.environ.get("SESSION_ID") or uuid.uuid4().hex[:12]
    )

    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


settings = Settings()
