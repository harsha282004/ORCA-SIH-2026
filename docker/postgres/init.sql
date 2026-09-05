-- Phase 0: infrastructure only. Enables PostGIS on first container boot.
-- No ORCA business tables are created here — that begins in Phase 1.
CREATE EXTENSION IF NOT EXISTS postgis;
