CREATE DATABASE bird;
-- The dump's timestamptz values were written on a UTC+8 server; without this
-- they read 8h off the SQLite originals and the gold queries return wrong rows.
ALTER DATABASE bird SET timezone = 'Asia/Shanghai';
\connect bird
CREATE EXTENSION IF NOT EXISTS pg_trgm;
