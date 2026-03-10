# autollm

Benchmark harness, AI optimizer agent, and dashboard for vLLM.

**Requires:** [runllm](runllm/) as a git submodule. Clone with `--recurse-submodules` or run `git submodule update --init` after clone.

## Quick start

```bash
git clone --recurse-submodules https://github.com/lukas/autollm
cd autollm

# One command: deploy vLLM, run benchmark, save to results/runs/[timestamp]
make benchmark

# Or run with a quick preset (5 requests, ~30s)
make benchmark BENCHMARK=quick
```

## make benchmark

Single command that:

1. Deploys vLLM (runllm)
2. Waits for model ready
3. Runs Guideline benchmark
4. Saves all output to `results/runs/YYYYMMDD_HHMMSS/`

```bash
make benchmark                              # full (200 req, ~10 min)
make benchmark BENCHMARK=quick              # quick (5 req, ~30s)
make benchmark BENCHMARK=sync               # sync (20 req, ~1 min)
make benchmark BENCHMARK=sweep               # sweep (60s, multiple profiles)
make benchmark BENCHMARK=quick DESCRIPTION="baseline"
```

**Presets:** `quick` (5 req), `sync` (20), `sweep` (60s), `full` (200 req)

**Run directory contents:** `run.log`, `vllm_config.yaml`, `pod_status.txt`, `run_metadata.json`, `benchmarks.json`, `benchmarks.csv`, `summary.html`

## Other targets

| Target | Description |
|--------|-------------|
| `make dashboard` | Start web dashboard at http://localhost:8765/ |
| `make benchmark-run` | Run benchmark only (requires port-forward) |
| `make ai-optimize` | AI optimizer (Claude/OpenAI suggests vLLM config changes) |

## Environment

- `KUBECONFIG` – Kubernetes config (required for `make benchmark`)
- `VLLM_CONFIG` – Path to vLLM YAML (default: `runllm/vllm-qwen.yaml`)
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` – For AI optimizer
- `AI_PROVIDER` – `anthropic` (default) or `openai`
