# autollm - Benchmark harness, AI optimizer, dashboard
# Requires: runllm submodule (runllm/) for vLLM config, vllm-qwen pod + port-forward

-include ../.env
-include .env

# Kubeconfig: copy to autollm/kubeconfig OR set KUBECONFIG_SERVER + KUBECONFIG_TOKEN in .env and run `make kubeconfig`
KUBECONFIG ?= $(CURDIR)/kubeconfig
export KUBECONFIG
export EXA_API_KEY

# Generate kubeconfig from .env (KUBECONFIG_SERVER, KUBECONFIG_TOKEN). kubeconfig is gitignored.
kubeconfig:
	@python3 scripts/gen_kubeconfig.py

BENCHMARK ?= medium
DESCRIPTION ?=

.PHONY: sync benchmark benchmark-run benchmark-run-quick sweep improve experiment experiment-inspect test-sweep-setup results-summary results-index dashboard ai-optimize query kubeconfig ensure-kubeconfig leaderboard sweep-pods backfill-names

ensure-kubeconfig:
	@test -f $(CURDIR)/kubeconfig || $(MAKE) kubeconfig

# Fast test (<5s): verify runllm apply runs delete before apply (no kubectl/network)
test-sweep-setup:
	@python3 scripts/test_sweep_setup.py

# Query vLLM (requires port-forward). Usage: make query PROMPT="Hello"
query:
	$(MAKE) -C runllm query PROMPT="$(PROMPT)"

# Install deps (unset VIRTUAL_ENV to avoid uv warning when parent cuda-play venv is active)
sync:
	env -u VIRTUAL_ENV uv sync --extra guidellm --extra ai_optimizer

# Guideline benchmarks (runllm forward in another terminal)
guidellm-bench: sync
	@echo "Run 'cd runllm && make forward' in another terminal first"
	mkdir -p results
	env -u VIRTUAL_ENV uv run guidellm benchmark \
		--target "http://localhost:8000" \
		--backend-args '{"http2":false}' \
		--profile sweep \
		--request-type chat_completions \
		--max-seconds 60 \
		--data "prompt_tokens=256,output_tokens=128" \
		--output-path results

guidellm-bench-quick: sync
	@echo "Run 'cd runllm && make forward' first"
	mkdir -p results
	env -u VIRTUAL_ENV uv run guidellm benchmark \
		--target "http://localhost:8000" \
		--backend-args '{"http2":false}' \
		--profile synchronous \
		--max-requests 20 --max-seconds 60 \
		--data "prompt_tokens=64,output_tokens=64" \
		--output-path results

# One-shot: start LLM, run Guideline benchmark, save to results/runs/YYYYMMDD_HHMMSS/
# Usage: make benchmark
#        make benchmark BENCHMARK=quick
#        make benchmark BENCHMARK=sweep DESCRIPTION="baseline"
# Presets: quick (5 req), sync (20 req), sweep (60s), full (200 req)
benchmark: sync ensure-kubeconfig
	@python3 scripts/benchmark_harness.py --start-llm --benchmark "$(BENCHMARK)" --description "$(DESCRIPTION)" $(if $(MAX_REQUESTS),--max-requests $(MAX_REQUESTS),) $(if $(MAX_SECONDS),--max-seconds $(MAX_SECONDS),)

# Harness: saves to results/runs/YYYYMMDD_HHMMSS/ (requires port-forward)
benchmark-run: sync
	@echo "Requires: cd runllm && make forward"
	VLLM_CONFIG=runllm/vllm-qwen.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)"

benchmark-run-quick: sync
	VLLM_CONFIG=runllm/vllm-qwen.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)" --skip-port-forward

# Results
results-summary:
	python3 scripts/benchmark_summary.py

results-index:
	python3 scripts/benchmark_harness.py --index-only

# Dashboard (Streamlit)
dashboard:
	env -u VIRTUAL_ENV uv sync --extra dashboard
	@echo ""
	@echo "Starting dashboard..."
	@echo ""
	env -u VIRTUAL_ENV uv run streamlit run scripts/dashboard.py --server.port 8765

# Start a new sweep: create results/sweep-[name]/, run baseline, save to baseline/
# Incomplete baselines (no benchmarks.json) are re-run automatically. Add FORCE=1 to overwrite complete baseline.
# Usage: make sweep SWEEP=my-sweep [BENCHMARK=quick] [FORCE=1]
sweep: BENCHMARK=quick
sweep: sync ensure-kubeconfig
	@env -u VIRTUAL_ENV uv run python scripts/start_sweep.py --sweep "$(SWEEP)" --benchmark "$(BENCHMARK)" $(if $(FORCE),--force,) $(if $(DATA),--data "$(DATA)",) $(if $(MAX_REQUESTS),--max-requests $(MAX_REQUESTS),) $(if $(MAX_SECONDS),--max-seconds $(MAX_SECONDS),) $(if $(GOAL),--goal "$(GOAL)",)

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

# AI optimizer (CLI)
ai-optimize: sync
	@echo "Requires: runllm forward, ANTHROPIC_API_KEY or OPENAI_API_KEY"
	VLLM_CONFIG=runllm/vllm-qwen.yaml env -u VIRTUAL_ENV uv run python scripts/ai_benchmark_optimizer.py
