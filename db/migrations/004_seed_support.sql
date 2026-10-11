-- Marks rows loaded from committed fixtures rather than fetched live, so the
-- egress report can distinguish "seeded" from "we actually called out".
ALTER TABLE pvwatts_cache  ADD COLUMN IF NOT EXISTS seeded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE geocode_cache  ADD COLUMN IF NOT EXISTS seeded BOOLEAN NOT NULL DEFAULT false;
