#!/usr/bin/env bash
# Fetch Pagila (pinned commit) and load it into database "pagila".
set -euo pipefail
cd "$(dirname "$0")/.."
REV=fef9675714cfba1756df4719b5e36075a7ddf90e  # tag pagila-v3.1.0; 4.x needs PostgreSQL 18
BASE=https://raw.githubusercontent.com/devrimgunduz/pagila/$REV
DIR=data/raw/pagila
mkdir -p "$DIR"
for f in pagila-schema.sql pagila-data.sql; do
  [ -f "$DIR/$f" ] || curl -sSfL "$BASE/$f" -o "$DIR/$f"
done

psql() { docker compose exec -T db psql -U postgres "$@"; }
if psql -d postgres -tAc "select 1 from pg_database where datname='pagila'" | grep -q 1; then
  echo "pagila already exists; drop it to reload"; exit 0
fi
psql -d postgres -qc "CREATE DATABASE pagila"
# Gold answers bucket timestamptz by month; pin the zone so they are stable.
psql -d postgres -qc "ALTER DATABASE pagila SET timezone = 'UTC'"
# Deterministic float aggregation and row order (see docker/initdb).
psql -d postgres -qc "ALTER DATABASE pagila SET max_parallel_workers_per_gather = 0"
psql -d postgres -qc "ALTER DATABASE pagila SET synchronize_seqscans = off"
psql -d pagila -qc "CREATE EXTENSION IF NOT EXISTS pg_trgm"
# Pagila's schema assigns ownership to role "postgres", which exists here.
psql -d pagila -q -v ON_ERROR_STOP=1 < "$DIR/pagila-schema.sql" >/dev/null
psql -d pagila -q -v ON_ERROR_STOP=1 < "$DIR/pagila-data.sql" >/dev/null
psql -d pagila -qc "ANALYZE"
psql -d pagila -tAc "select count(*) || ' tables loaded' from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"
