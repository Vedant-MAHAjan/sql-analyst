#!/usr/bin/env bash
# Load the Mini-Dev PostgreSQL dump into the compose db (database "bird").
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP=data/raw/minidev/minidev/MINIDEV_postgresql/BIRD_dev.sql

n=$(docker compose exec -T db psql -U postgres -d bird -tAc \
  "select count(*) from information_schema.tables where table_schema='public'")
if [ "$n" -gt 0 ]; then
  echo "bird already has $n tables; drop the volume to reload"; exit 0
fi

# The dump assigns ownership to the BIRD authors' local role; drop those lines.
grep -v ' OWNER TO ' "$DUMP" |
  docker compose exec -T db psql -U postgres -d bird -q -v ON_ERROR_STOP=1 >/dev/null
docker compose exec -T db psql -U postgres -d bird -c "ANALYZE" >/dev/null
docker compose exec -T db psql -U postgres -d bird -tAc \
  "select count(*) || ' tables loaded' from information_schema.tables where table_schema='public'"
