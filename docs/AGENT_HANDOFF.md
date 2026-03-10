# Agent Handoff: AI Benchmark Optimizer

**Purpose:** Handoff document for an agent to quickly understand and continue work on the AI-driven vLLM benchmark optimizer.

---

## What Exists

### 1. AI Benchmark Optimizer (`scripts/ai_benchmark_optimizer.py`)

Uses Claude Opus or OpenAI GPT-5/Codex to suggest vLLM config changes, applies them, restarts the pod, runs benchmarks, and compares before/after.

- **Claude (default):** `claude-opus-4-6` — requires `ANTHROPIC_API_KEY`
- **OpenAI:** `gpt-5.4` or `gpt-5-codex` — requires `OPENAI_API_KEY` + `AI_PROVIDER=openai`
- **gpt-5-codex** uses the Responses API only (not Chat Completions) — script branches on `"codex"` in model name

### 2. Live Dashboard (`results/ai_optimizer.html`)

Web dashboard that shows:
- Live status during runs: step, strategy being tried, changes summary
- History of all attempts: timestamp, strategy, before/after metrics, links to run reports
- Polls `results/ai_optimizer_state.json` every 2 seconds

### 3. State File (`results/ai_optimizer_state.json`)

Written by the optimizer script at each step. Structure:
```json
{
  "current_run": { "status": "...", "step": "...", "strategy": "...", "provider": "...", "model": "..." },
  "history": [{ "timestamp": "...", "run_path": "runs/YYYYMMDD_HHMMSS", "strategy": "...", "before_metrics": "...", "after_metrics": "..." }]
}
```

### 4. Benchmark Harness (`scripts/benchmark_harness.py`)

Runs Guideline benchmarks, saves to `results/runs/YYYYMMDD_HHMMSS/`. The AI optimizer calls this after applying config.

---

## Key Files

| Path | Purpose |
|------|---------|
| `scripts/ai_benchmark_optimizer.py` | Main AI optimizer: calls LLM, applies config, restarts pod, runs benchmark |
| `scripts/benchmark_harness.py` | Benchmark runner; saves runs with timestamped dirs |
| `results/ai_optimizer.html` | Live dashboard (open via `make results-serve`) |
| `results/ai_optimizer_state.json` | Live state + history (written by optimizer) |
| `vllm-qwen.yaml` | vLLM pod config (modified by optimizer, then restored) |
| `docs/BENCHMARK_HARNESS.md` | Full docs for harness + AI optimizer |

---

## How to Run

```bash
# 1. Start results server (for dashboard)
make results-serve
# Open http://localhost:8765/ai_optimizer.html

# 2. In another terminal, run optimizer
make ai-benchmark-optimize

# Or with OpenAI/Codex:
AI_PROVIDER=openai AI_MODEL=gpt-5-codex make ai-benchmark-optimize
```

**Dependencies:** `uv sync --extra guidellm --extra ai_optimizer` (Makefile does this)

---

## Flow

1. Read `vllm-qwen.yaml` + latest benchmark from `results/runs/` or `results/benchmarks.json`
2. Call AI with prompt (config + metrics); ask for `Strategy:` line + modified YAML
3. Parse YAML from response; extract strategy
4. Backup config, write new YAML
5. `kubectl delete pod vllm-qwen` → `kubectl apply -f vllm-qwen.yaml` → `kubectl wait` (5 min)
6. Run `scripts/benchmark_harness.py` with description `"AI suggestion (provider)"`
7. Compare metrics; append to `history`; restore original config

---

## Environment

- `.env` — may contain `HF_TOKEN`, `MODEL`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` required
- `KUBECONFIG` — set in Makefile for k8s access (vLLM runs on cluster)

---

## Gotchas / Known Issues

1. **kubectl wait timeout:** Must use `--timeout=300s` (with `s` suffix), not `300`
2. **gpt-5-codex:** Only supported in Responses API; script uses `client.responses.create()` when `"codex"` in model name
3. **AI prompt:** Asks for `Strategy: <one-liner>` before the YAML block; parsed with regex
4. **Config restore:** Original config is always restored at end; AI version saved to `vllm-qwen.yaml.bak`

---

## Possible Next Work

- Run optimization in a loop (multiple iterations)
- Add improvement % to history (parse before/after to compute delta)
- Support multiple vLLM configs (e.g. `vllm-kimi.yaml`)
- Add `--dry-run` to show suggested changes without applying
- Improve strategy extraction when AI doesn't follow format
