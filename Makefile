# autollm - Benchmark harness, AI optimizer, dashboard
# Requires: runllm (sibling) for vLLM config, vllm-qwen pod + port-forward

-include ../.env
-include .env

.PHONY: sync bench bench-quick benchmark-run benchmark-run-quick results-summary results-index serve dashboard ai-optimize

# Install deps
sync:
	uv sync --extra guidellm --extra ai_optimizer

# Guideline benchmarks (runllm forward in another terminal)
guidellm-bench: sync
	@echo "Run 'cd runllm && make forward' in another terminal first"
	mkdir -p results
	uv run guidellm benchmark \
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
	uv run guidellm benchmark \
		--target "http://localhost:8000" \
		--backend-args '{"http2":false}' \
		--profile synchronous \
		--max-requests 20 --max-seconds 60 \
		--data "prompt_tokens=64,output_tokens=64" \
		--output-path results

# Harness: saves to results/runs/YYYYMMDD_HHMMSS/
benchmark-run: sync
	@echo "Requires: cd runllm && make forward"
	VLLM_CONFIG=../runllm/vllm-qwen.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)"

benchmark-run-quick: sync
	VLLM_CONFIG=../runllm/vllm-qwen.yaml python3 scripts/benchmark_harness.py --description "$(DESCRIPTION)" --skip-port-forward

# Results
results-summary:
	python3 scripts/benchmark_summary.py

results-index:
	python3 scripts/benchmark_harness.py --index-only

# Serve dashboard
serve: results-summary results-index
	@mkdir -p results
	@echo "Serving at http://localhost:8765/"
	python3 scripts/serve_results.py

# Dashboard (reset + serve)
dashboard:
	python3 scripts/dashboard_reset.py
	@mkdir -p results
	@echo ""
	@echo "Dashboard: http://localhost:8765/"
	@echo "  Start/Stop · Output · Benchmark runs"
	@echo ""
	python3 scripts/serve_results.py

# AI optimizer (CLI)
ai-optimize: sync
	@echo "Requires: runllm forward, ANTHROPIC_API_KEY or OPENAI_API_KEY"
	VLLM_CONFIG=../runllm/vllm-qwen.yaml uv run python scripts/ai_benchmark_optimizer.py
