# make setup      - database up, data downloaded and loaded, value indexes built
# make reproduce  - re-execute and re-score the committed predictions (no model needed)
# make smoke      - 60-question regression gate (needs Ollama for uncached calls)
# make attacks    - Phase 5 attack suite (needs Ollama)
PY := .venv/bin/python

.PHONY: setup reproduce smoke attacks cache serve

.venv:
	python3.11 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

setup: .venv
	docker compose up -d --wait
	$(PY) -I data/fetch_minidev.py
	./data/load_minidev.sh
	./data/load_pagila.sh
	$(PY) -m agent.value_index build

runs/cache:
	mkdir -p runs && tar -xzf data/model_cache.tar.gz -C runs

reproduce: .venv
	$(PY) -m eval.reproduce

smoke: .venv runs/cache
	$(PY) -m eval.smoke_gate

attacks: .venv
	./data/setup_attack_dbs.sh
	$(PY) -m eval.attack_suite full

cache:  # refresh the committed cache after new runs
	tar -czf data/model_cache.tar.gz -C runs cache

serve: .venv
	.venv/bin/uvicorn serve.api:app --port 8008
