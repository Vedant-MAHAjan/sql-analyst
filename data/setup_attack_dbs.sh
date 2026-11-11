#!/usr/bin/env bash
# Clone bird -> bird_attack and pagila -> pagila_attack, plant prompt injections,
# and rebuild their value indexes. Attacks only ever run against these copies.
set -euo pipefail
cd "$(dirname "$0")/.."
psql() { docker compose exec -T db psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }

for pair in bird:bird_attack pagila:pagila_attack; do
  src=${pair%%:*}; dst=${pair##*:}
  psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                       WHERE datname IN ('$src', '$dst') AND pid <> pg_backend_pid()" >/dev/null
  psql -d postgres -c "DROP DATABASE IF EXISTS $dst"
  psql -d postgres -c "CREATE DATABASE $dst TEMPLATE $src"
  # Per-database settings are not copied by TEMPLATE.
  tz=$([ "$src" = bird ] && echo Asia/Shanghai || echo UTC)
  psql -d postgres -c "ALTER DATABASE $dst SET timezone = '$tz'"
  psql -d postgres -c "ALTER DATABASE $dst SET max_parallel_workers_per_gather = 0"
  psql -d postgres -c "ALTER DATABASE $dst SET synchronize_seqscans = off"
done
psql -d bird_attack < eval/attacks/plant_bird.sql
psql -d pagila_attack < eval/attacks/plant_pagila.sql
.venv/bin/python -m agent.value_index build-attack
echo "attack databases ready"
