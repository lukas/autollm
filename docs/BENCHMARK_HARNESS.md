# Benchmark Test Harness

The test harness runs Guideline benchmarks against your vLLM setup, saves every run to a unique directory, and provides a browsable history. No run is ever overwritten.

## Quick Start

1. Ensure the `vllm-qwen` pod is running (`kubectl get pod vllm-qwen`)
2. Run a benchmark:
   ```bash
   make benchmark-run
   ```
3. View results: `make results-serve` then open http://localhost:8765/runs/index.html

## Workflow: Modify vLLM → Benchmark → Compare

### 1. Make a change to vLLM

Edit `vllm-qwen.yaml` (e.g., change model, tensor-parallel-size, or other args):

```yaml
# Example: try a different model
args:
  - "--model"
  - "Qwen/Qwen2.5-3B-Instruct"
  - "--tensor-parallel-size"
  - "1"
```

Apply if the pod needs to change:
```bash
kubectl delete pod vllm-qwen
kubectl apply -f vllm-qwen.yaml
kubectl wait --for=condition=Ready pod/vllm-qwen --timeout=300s
```

### 2. Run the benchmark

```bash
# Full run (starts port-forward, runs benchmark, stops port-forward)
make benchmark-run DESCRIPTION="Qwen 3B baseline"

# Or, if port-forward is already running in another terminal:
make benchmark-run-quick DESCRIPTION="Qwen 3B baseline"
```

### 3. View results

Each run is saved to `results/runs/YYYYMMDD_HHMMSS/`:

- **summary.html** — Latency, TTFT, ITL, throughput
- **benchmarks.html** — Guideline full report
- **vllm_config.yaml** — vLLM config at run time
- **pod_status.txt** — Pod state
- **run.log** — Benchmark log

Serve and browse:
```bash
make results-serve
# Open http://localhost:8765/runs/index.html
```

The index lists all runs with metrics and links. Use it to compare configurations.

## Commands Reference

| Command | Description |
|---------|-------------|
| `make benchmark-run` | Run benchmark (starts port-forward automatically) |
| `make benchmark-run DESCRIPTION="label"` | Run with a description for the index |
| `make benchmark-run-quick` | Same, but assumes port-forward already running |
| `make benchmark-import` | Copy current `results/` into a new run (preserve pre-harness history) |
| `make results-serve` | Serve results at http://localhost:8765/ |
| `make results-index` | Rebuild the runs index (e.g., after manual copy) |

## Run Directory Contents

| File | Description |
|------|-------------|
| `benchmarks.json` | Guideline raw output |
| `benchmarks.csv` | Tabular metrics |
| `benchmarks.html` | Guideline interactive report |
| `summary.html` | Simple metrics table (latency, TTFT, ITL, throughput) |
| `vllm_config.yaml` | Copy of `vllm-qwen.yaml` at run time |
| `pod_status.txt` | `kubectl describe pod vllm-qwen` |
| `run_metadata.json` | Timestamp, description |
| `run.log` | Harness log + Guideline stdout/stderr |

## AI-Driven Optimization

Use Claude Opus or OpenAI to suggest vLLM config changes, run the benchmark, and compare:

```bash
# Claude Opus (default) - requires ANTHROPIC_API_KEY
make ai-benchmark-optimize

# OpenAI (GPT-5.4) - requires OPENAI_API_KEY
AI_PROVIDER=openai make ai-benchmark-optimize

# Use Claude Sonnet instead of Opus (cheaper)
AI_MODEL=claude-sonnet-4-20250514 make ai-benchmark-optimize
```

The AI receives your current `vllm-qwen.yaml` and latest benchmark metrics, proposes a modification (e.g., `--max-model-len`, `--gpu-memory-utilization`, different model), and the script applies it, restarts the pod, runs the benchmark, and prints a before/after comparison. Original config is restored at the end; the AI version is backed up to `vllm-qwen.yaml.bak`.

Dependencies: `uv sync --extra ai_optimizer` (anthropic, openai) — the Makefile target runs this automatically.

**Live dashboard:** Start `make results-serve` in one terminal, then run `make ai-benchmark-optimize` in another. Open http://localhost:8765/ai_optimizer.html to see live updates on the agent's strategy, current step, and history of all attempts with before/after metrics.

**Agent handoff:** See [AGENT_HANDOFF.md](AGENT_HANDOFF.md) for a concise summary so another agent can pick up this work quickly.

## Tips

- **Label runs:** Always use `DESCRIPTION=` so you can tell runs apart in the index
- **Port-forward:** Use `benchmark-run-quick` when iterating; keep `make vllm-qwen-forward` running in a separate terminal
- **Import old results:** If you have benchmarks in `results/` from before the harness, run `make benchmark-import DESCRIPTION="pre-harness baseline"` to save them
- **Compare configs:** Open `vllm_config.yaml` from different runs to diff vLLM settings
