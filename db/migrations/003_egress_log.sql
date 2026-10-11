-- Every byte that leaves this machine is recorded here. `make egress-report`
-- reads it. session_id scopes the report to one demo run, so the table does not
-- accumulate every rehearsal into the number we quote on stage.

CREATE TABLE IF NOT EXISTS egress_log (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id  TEXT NOT NULL DEFAULT 'default',
  service     TEXT NOT NULL,
  host        TEXT NOT NULL,
  path        TEXT NOT NULL,
  params_sent JSONB NOT NULL,
  status      INT,
  cache_hit   BOOLEAN NOT NULL DEFAULT false,
  duration_ms INT
);
CREATE INDEX IF NOT EXISTS egress_log_session_idx ON egress_log (session_id, ts DESC);
