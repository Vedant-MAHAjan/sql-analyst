CREATE DATABASE bird;
-- The dump's timestamptz values were written on a UTC+8 server; without this
-- they read 8h off the SQLite originals and the gold queries return wrong rows.
ALTER DATABASE bird SET timezone = 'Asia/Shanghai';
-- Parallel aggregation reorders float sums, so AVG/SUM differ in the last bit
-- between runs and exact-match EX flips at random; scans also reorder rows.
ALTER DATABASE bird SET max_parallel_workers_per_gather = 0;
ALTER DATABASE bird SET synchronize_seqscans = off;
\connect bird
CREATE EXTENSION IF NOT EXISTS pg_trgm;
