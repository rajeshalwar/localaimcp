-- Cache tables exist so that a repeated question costs zero egress.
-- They are also what makes REPLAY_ONLY (demo with the network down) possible.

CREATE TABLE IF NOT EXISTS pvwatts_cache (
  cache_key  TEXT PRIMARY KEY,
  lat_r      NUMERIC(6,3) NOT NULL,
  lon_r      NUMERIC(6,3) NOT NULL,
  params     JSONB NOT NULL,
  response   JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geocode_cache (
  address_norm TEXT PRIMARY KEY,
  response     JSONB NOT NULL,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
