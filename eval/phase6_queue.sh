#!/usr/bin/env bash
# Phase 6 run queue (sequential: one Ollama). Model calls are cached, so a
# rerun after an interruption only pays for what is missing.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
run() { echo "=== $*"; $PY -m eval.runner "$@" | tail -2; }

run eval/configs/agent_noevidence.yaml
run eval/configs/agent_7b_evidence.yaml
run eval/configs/agent_tiered_noevidence.yaml
# ~3 model calls per question: a fixed 200-question stratified sample (seed 0).
run eval/configs/agent_planner_critic_evidence.yaml --sample 200
for s in 1 2 3 4; do  # pass^4: same 100 questions, temperature 0.7, four seeds
  run eval/configs/agent_evidence.yaml --sample 100 \
    --set model.options.temperature=0.7 --set model.options.seed=$s
done
echo "=== held-out"
$PY -m eval.freeze check || { echo "prompts changed since freeze; not running held-out"; exit 1; }
run eval/configs/heldout_baseline.yaml
run eval/configs/heldout_agent.yaml
echo "=== done"
