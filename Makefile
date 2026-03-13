# autollm - Benchmark harness, AI optimizer, dashboard
# Requires: runllm submodule (runllm/<model>/) for vLLM config

-include ../.env
-include .env

# Kubeconfig: copy to autollm/kubeconfig OR set KUBECONFIG_SERVER + KUBECONFIG_TOKEN in .env and run `make kubeconfig`
KUBECONFIG ?= $(CURDIR)/kubeconfig
export KUBECONFIG
export EXA_API_KEY

# Default model directory under runllm/
MODEL_DIR ?= qwen2.5-1.5b

# Generate kubeconfig from .env (KUBECONFIG_SERVER, KUBECONFIG_TOKEN). kubeconfig is gitignored.
kubeconfig:
	@python3 scripts/gen_kubeconfig.py

BENCHMARK ?= medium
DESCRIPTION ?=

.PHONY: sync benchmark benchmark-run benchmark-run-quick sweep full-sweep improve experiment experiment-inspect test-sweep-setup results-summary results-index dashboard query kubeconfig ensure-kubeconfig leaderboard sweep-pods backfill-names tensorize sweep-remote sync-results sweep-logs sweep-status sweep-remote-teardown

ensure-kubeconfig:
	@test -f $(CURDIR)/kubeconfig || $(MAKE) kubeconfig

# Fast test (<5s): verify runllm apply runs delete before apply (no kubectl/network)
test-sweep-setup:
	@python3 scripts/test_sweep_setup.py

# Query vLLM (requires port-forward). Usage: make query PROMPT="Hello"
query:
	$(MAKE) -C runllm/$(MODEL_DIR) query PROMPT="$(PROMPT)"

# Install deps (unset VIRTUAL_ENV to avoid uv warning when parent cuda-play venv is active)
sync:
	env -u VIRTUAL_ENV uv sync --extra guidellm --extra ai_optimizer

# One-shot: start LLM, run Guideline benchmark, save to results/runs/YYYYMMDD_HHMMSS/
# Usage: make benchmark
#        make benchmark BENCHMARK=quick
#        make benchmark BENCHMARK=sweep DESCRIPTION="baseline"
# Presets: quick (5 req), sync (20 req), sweep (60s), full (200 req)
benchmark: sync ensure-kubeconfig
	@VLLM_CONFIG=runllm/$(MODEL_DIR)/vllm-config.yaml python3 scripts/benchmark_harness.py --start-llm --benchmark "$(BENCHMARK)" --description "$(DESCRIPTION)" $(if $(MAX_REQUESTS),--max-requests $(MAX_REQUESTS),) $(if $(MAX_SECONDS),--max-seconds $(MAX_SECONDS),)

# Harness: saves to results/runs/YYYYMMDD_HHMMSS/ (requires port-forward)
benchmark-run: sync
	@echo "Requires: cd runllm/$(MODEL_DIR) && make forward"
	VLLM_CONFIG=runllm/$(MODEL_DIR)/vllm-config.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)"

benchmark-run-quick: sync
	VLLM_CONFIG=runllm/$(MODEL_DIR)/vllm-config.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)" --skip-port-forward

# Results
results-summary:
	python3 scripts/benchmark_summary.py

results-index:
	python3 scripts/benchmark_harness.py --index-only

# Dashboard (Streamlit) — sync all extras to avoid uv uninstalling streamlit static assets
dashboard:
	env -u VIRTUAL_ENV uv sync --extra dashboard --extra guidellm --extra ai_optimizer
	@echo ""
	@echo "Starting dashboard..."
	@echo ""
	env -u VIRTUAL_ENV uv run streamlit run scripts/dashboard.py --server.port 8765

# Start a new sweep: create results/sweep-[name]/, run baseline, save to baseline/
# Incomplete baselines (no benchmarks.json) are re-run automatically. Add FORCE=1 to overwrite complete baseline.
# Usage: make sweep SWEEP=my-sweep [BENCHMARK=quick] [FORCE=1]
#        make sweep SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b GOAL="maximize throughput"
sweep: BENCHMARK=quick
sweep: sync ensure-kubeconfig
	@env -u VIRTUAL_ENV uv run python scripts/start_sweep.py --sweep "$(SWEEP)" --model-dir "$(MODEL_DIR)" --benchmark "$(BENCHMARK)" $(if $(FORCE),--force,) $(if $(DATA),--data "$(DATA)",) $(if $(MAX_REQUESTS),--max-requests $(MAX_REQUESTS),) $(if $(MAX_SECONDS),--max-seconds $(MAX_SECONDS),) $(if $(GOAL),--goal "$(GOAL)",)

# Full sweep: create sweep + run baseline, then run N improvement iterations
# Usage: make full-sweep SWEEP=my-sweep RUNS=5
#        make full-sweep SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b RUNS=10 GOAL="maximize throughput"
full-sweep: sweep
	@$(MAKE) improve SWEEP="$(SWEEP)" RUNS="$(RUNS)" $(if $(ALLOW_MODEL_CHANGE),ALLOW_MODEL_CHANGE=1,)

# Refresh leaderboard in sweep dir (also written automatically during improve runs)
# Usage: make leaderboard SWEEP=my-sweep
leaderboard:
	@test -n "$(SWEEP)" || (echo "Usage: make leaderboard SWEEP=name"; exit 1)
	env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --refresh-leaderboard --sweep "$(SWEEP)"

# List running Kubernetes pods associated with a sweep
# Usage: make sweep-pods SWEEP=my-sweep
sweep-pods: ensure-kubeconfig
	@test -n "$(SWEEP)" || (echo "Usage: make sweep-pods SWEEP=name"; exit 1)
	env -u VIRTUAL_ENV uv run python scripts/list_sweep_pods.py --sweep "$(SWEEP)"

# Improve a sweep: LLM suggests vLLM changes, deploy, benchmark, save to results/sweep-[name]/[timestamp]/
# Includes modified runllm snapshot. Requires sweep baseline first.
# Usage: make improve SWEEP=my-sweep
#        make improve SWEEP=my-sweep RUNS=5        # run 5 improvement iterations
#        make improve SWEEP=my-sweep RUNS=5 ALLOW_MODEL_CHANGE=1
RUNS ?= 1
improve: BENCHMARK=quick
improve: sync ensure-kubeconfig
	@for i in $$(seq 1 $(RUNS)); do \
		echo ""; echo "══════════════════════════════════════════"; \
		echo "  Improvement run $$i/$(RUNS)"; \
		echo "══════════════════════════════════════════"; \
		env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --sweep "$(SWEEP)" $(if $(ALLOW_MODEL_CHANGE),--allow-model-change,) || true; \
	done

# AI experiment (standalone, no sweep): agent suggests changes, deploy, benchmark
# Saves to results/runs/exp_[ts]. For sweep-based flow, use 'make improve SWEEP=name'
# Default: quick. Override: make experiment BENCHMARK=sync|sweep|medium|long
experiment: BENCHMARK=quick
experiment: sync ensure-kubeconfig
	@env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py $(if $(ALLOW_MODEL_CHANGE),--allow-model-change,)

# Inspect experiment progress (run in another terminal while 'make experiment' or 'make improve' runs)
# After 3 min, use 'make experiment-inspect KILL=1' to abort if stuck
experiment-inspect:
	@env -u VIRTUAL_ENV uv run python scripts/experiment_inspect.py $(if $(KILL),--kill,)

# Backfill short names for runs that don't have one (uses gpt-4o-mini by default)
backfill-names: sync
	env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py backfill-names

# Serialize model weights to PVC via Tensorizer (one-time per model, idempotent).
# Usage: make tensorize MODEL_DIR=qwen3-235b
#        make tensorize MODEL_DIR=kimi
tensorize: ensure-kubeconfig
	$(MAKE) -C runllm/$(MODEL_DIR) tensorize

# ── Remote sweep (runs on a K8s controller pod) ──────────────────────────────
# Start a sweep on a remote controller pod (agent + benchmarks run in-cluster).
# The controller pod is created once and reused. Code is synced from local.
# Usage: make sweep-remote SWEEP=my-sweep RUNS=10 GOAL="maximize throughput"
#        make sweep-remote SWEEP=qwen3-235b MODEL_DIR=qwen3-235b BENCHMARK=medium-throughput RUNS=30
sweep-remote: ensure-kubeconfig
	@scripts/sweep_remote.sh start \
		--sweep "$(SWEEP)" --model-dir "$(MODEL_DIR)" --benchmark "$(BENCHMARK)" \
		--runs "$(RUNS)" $(if $(GOAL),--goal "$(GOAL)",) $(if $(FORCE),--force,)

# Copy sweep results from the remote controller pod to local machine.
# Usage: make sync-results SWEEP=my-sweep     # sync one sweep
#        make sync-results                     # sync all results
sync-results: ensure-kubeconfig
	@scripts/sweep_remote.sh sync $(if $(SWEEP),--sweep "$(SWEEP)",)

# Tail live output from the most recent remote sweep.
sweep-logs: ensure-kubeconfig
	@scripts/sweep_remote.sh logs

# Check status of remote sweeps on the controller pod.
sweep-status: ensure-kubeconfig
	@scripts/sweep_remote.sh status

# Delete the remote controller pod (results are lost unless synced first!).
sweep-remote-teardown: ensure-kubeconfig
	@scripts/sweep_remote.sh teardown
