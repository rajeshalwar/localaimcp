CREATE TABLE IF NOT EXISTS assessments (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  address_input   TEXT NOT NULL,
  matched_address TEXT,
  lat             NUMERIC(9,6) NOT NULL,
  lon             NUMERIC(9,6) NOT NULL,
  county          TEXT,
  inputs          JSONB NOT NULL,
  results         JSONB NOT NULL,
  summary         TEXT
);
CREATE INDEX IF NOT EXISTS assessments_created_idx ON assessments (created_at DESC);
