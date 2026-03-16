# Benchmark Test Harness

The test harness runs Guideline benchmarks against your vLLM setup, saves every run to a unique directory, and provides a browsable history. No run is ever overwritten.

## Quick Start

1. Ensure cluster access is configured (`make kubeconfig` or export `KUBECONFIG`)
2. Run a benchmark:
   ```bash
   make benchmark
   ```
3. View results: `make dashboard` then open http://localhost:8765/

## Workflow: Modify vLLM → Benchmark → Compare

### 1. Make a change to vLLM

Edit the model config in `runllm/<model>/vllm-config.yaml` (e.g., change args, tensor-parallel-size):

```yaml
# Example: try a different setting
args:
  - "--model"
  - "Qwen/Qwen2.5-1.5B-Instruct"
  - "--tensor-parallel-size"
  - "1"
```

Apply if the pod needs to change:
```bash
cd runllm/qwen2.5-1.5b
make apply
```

### 2. Run the benchmark

```bash
# Full run (deploys with runllm/, runs benchmark, saves results/runs/YYYYMMDD_HHMMSS/)
make benchmark DESCRIPTION="Qwen 1.5B baseline"

# With a different model:
make benchmark MODEL_DIR=qwen3-235b DESCRIPTION="Qwen3 235B baseline"

# Quick preset:
make benchmark BENCHMARK=quick DESCRIPTION="quick check"
```

### 3. View results

Each run is saved to `results/runs/YYYYMMDD_HHMMSS/`:

- **summary.html** — Latency, TTFT, ITL, throughput
- **benchmarks.html** — Guideline full report
- **vllm_config.yaml** — vLLM config at run time
- **pod_status.txt** — Pod state
- **run.log** — Benchmark log

View in the dashboard:
```bash
make dashboard
# Open http://localhost:8765/
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `make benchmark` | Deploy + run benchmark and save a timestamped run |
| `make benchmark BENCHMARK=quick` | Quick preset |
| `make benchmark MODEL_DIR=qwen3-235b` | Benchmark a different model |
| `make benchmark-run` | Run harness only (assumes port-forward exists) |
| `make benchmark-run-quick` | Run harness only with `--skip-port-forward` |
| `make dashboard` | Streamlit dashboard at http://localhost:8765/ |
| `make results-index` | Rebuild the runs index (e.g., after manual copy) |

## Run Directory Contents

| File | Description |
|------|-------------|
| `benchmarks.json` | Guideline raw output |
| `benchmarks.csv` | Tabular metrics |
| `benchmarks.html` | Guideline interactive report |
| `summary.html` | Simple metrics table (latency, TTFT, ITL, throughput) |
| `vllm_config.yaml` | Copy of `vllm-config.yaml` at run time |
| `pod_status.txt` | `kubectl describe pod` output |
| `hardware_context.json` | Pod placement plus resource requests/limits captured for profiling |
| `vllm_metrics.txt` | Final raw scrape of vLLM Prometheus `/metrics` |
| `vllm_metrics_summary.json` | Final parsed subset of important vLLM metrics |
| `vllm_metrics_timeseries.jsonl` | Periodic `/metrics` samples taken during the benchmark |
| `gpu_metrics_timeseries.jsonl` | Best-effort `nvidia-smi` samples during the benchmark, if available in the container |
| `vllm_metrics_profile.json` | Compact profile summary: cache pressure, queue depth, throughput, GPU usage, diagnosis hints |
| `run_metadata.json` | Timestamp, description |
| `run.log` | Harness log + Guideline stdout/stderr |
| `RETRO.md` | Agent-written retrospective (every sweep run) |

## AI-Driven Optimization

Use the sweep workflow to let the agent iterate on vLLM config changes:

```bash
make sweep SWEEP=qwen-latency MODEL_DIR=qwen2.5-1.5b GOAL="minimize latency"
make sweep SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b GOAL="maximize throughput"
make improve SWEEP=qwen-latency
make leaderboard SWEEP=qwen-latency
```

Each improve run copies the current best model config, uses tools to research and propose an experiment, deploys it, benchmarks it, and writes a `RETRO.md` with lessons learned. Sweep artifacts are saved under `results/sweep-NAME/`.

Sweep-local research memory:
- `RESEARCH_LOG.md` records external research (`search_web` / `fetch_url`) done during the sweep.
- `RESEARCH_MEMORY.md` is a cached synthesis of that log and is included in later improve prompts.
- This lets the agent do more web research when useful without paying to rediscover the same facts every run.
- If a deploy fails because the pod is unschedulable or GPUs are unavailable, the improve loop now treats that as a cluster-capacity failure and stops instead of spending retries on config repairs.

For long sweeps, run the full sweep remotely inside the cluster:

```bash
make sweep-remote SWEEP=qwen3-throughput MODEL_DIR=qwen3-235b BENCHMARK=large RUNS=100 GOAL="maximize throughput"
make sweep-logs          # tail live output
make sweep-status        # check running sweeps
make sync-results SWEEP=qwen3-throughput  # pull results to local
```

Remote sweep lifecycle notes:
- `make sweep-status` now treats zombie controller-side shell PIDs as finished work and removes stale pid files while reporting status.
- Each background sweep runs through a small launcher wrapper that deletes `/workspace/sweep-<name>.pid` on exit and records `/workspace/sweep-<name>.exit_code`.
- The controller pod spec now includes a simple reaper loop for orphaned child processes. If you already have a long-lived controller pod running, recreate it after your active sweeps finish to pick up that reaping behavior.
- `make sync-results SWEEP=...` refreshes top-level sweep memory artifacts too, including `FULL_RETRO.txt` and `RESEARCH_MEMORY.md`, so local inspection stays aligned with the controller-side agent context.

Both `make benchmark` and `make improve` collect lightweight run profiling automatically. The profiler samples vLLM's built-in Prometheus endpoint every few seconds during the benchmark and writes a compact summary plus raw JSONL timeseries. If `nvidia-smi` is available inside the pod, GPU utilization, memory use, temperature, and power draw are also sampled.

**Agent handoff:** See [AGENT_HANDOFF.md](AGENT_HANDOFF.md) for a concise summary so another agent can pick up this work quickly.

Useful env vars for agent behavior:
- `AGENT_MAX_TURNS` controls total tool calls per improve run (default `50`).
- `AGENT_MAX_WEB_TOOL_CALLS` controls `search_web` / `fetch_url` calls per improve run (default `20`).

## Tips

- **Label runs:** Always use `DESCRIPTION=` so you can tell runs apart in the index
- **Port-forward:** Use `benchmark-run` or `benchmark-run-quick` when iterating against an already-running pod
- **Compare configs:** Open `vllm_config.yaml` from different runs to diff vLLM settings
- **Profile bottlenecks:** Check `vllm_metrics_profile.json` first. It highlights queue buildup, KV cache pressure, preemption growth, and whether GPU utilization stayed low.
