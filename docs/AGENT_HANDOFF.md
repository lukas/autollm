# Agent Handoff: autollm Sweep Workflow

**Purpose:** durable context for future agents working on `autollm`. Read this before changing sweep/improve behavior, benchmark flow, or `runllm` integration.

---

## Current Primary Workflow

The main path is the sweep workflow, not the older dashboard optimizer:

```bash
make sweep SWEEP=qwen-latency GOAL="minimize latency"
make improve SWEEP=qwen-latency
make leaderboard SWEEP=qwen-latency
make sweep-pods SWEEP=qwen-latency
```

- `make sweep` creates `results/sweep-NAME/`, runs a baseline, writes `sweep_metadata.json`, creates `best-runllm`, and writes `leaderboard.txt`.
- `make improve` runs `scripts/ai_experiment.py`, which copies the current best `runllm`, prompts the LLM, deploys a unique pod, runs a sample query, benchmarks it, and updates the sweep artifacts.
- `make leaderboard` refreshes `results/sweep-NAME/leaderboard.txt`.
- `make sweep-pods` lists currently running pods labeled for a sweep.

The older `scripts/ai_benchmark_optimizer.py` / dashboard flow still exists, but it is no longer the main tuning workflow.

---

## Important Files

| Path | Purpose |
|------|---------|
| `scripts/ai_experiment.py` | Main sweep improve loop, prompt construction, deploy/benchmark, retries, retro writing, cleanup |
| `scripts/agent_tools.py` | Tool definitions, execution engine, and provider-agnostic agent loop (Anthropic + OpenAI) |
| `scripts/benchmark_config.py` | Shared benchmark presets and Guideline progress parsing helpers |
| `scripts/benchmark_harness.py` | One-shot benchmark harness for `results/runs/` |
| `scripts/run_guideline_experiment.py` | Guideline subprocess wrapper for experiment mode; writes `query_progress.json` |
| `scripts/start_sweep.py` | Baseline sweep creation |
| `scripts/sweep_utils.py` | Best-run scoring and objective helpers |
| `runllm/` | Canonical vLLM deploy/query/test surface used by `autollm` |
| `docs/BENCHMARK_HARNESS.md` | Current harness and sweep docs |

---

## Behavior That Was Intentionally Added

### Leaderboard / Prompting

- `results/sweep-NAME/leaderboard.txt` is written automatically during sweep setup and improve runs.
- Leaderboards now rank by sweep objective:
  - `latency` sweeps: lower latency first
  - `throughput` sweeps: higher throughput first
  - `ttft` sweeps: lower TTFT first
- The leaderboard includes:
  - full strategy text
  - structured `Changed knobs vs baseline`
  - full arg summaries extracted from YAML using structured parsing, not fragile regex
- Prompt guidance pushes the agent toward single-change experiments and allows `NO_CONFIG_CHANGE: ...` on retries when logs suggest a harness/watchdog issue rather than a config issue.

### Tool-Calling Agent

- The agent now uses a full tool stack defined in `scripts/agent_tools.py` (10 tools: `search_web`, `fetch_url`, `read_file`, `write_file`, `list_files`, `run_shell`, `run_benchmark`, `read_logs`, `kubectl_get`, `kubectl_logs`).
- `run_agent()` in `agent_tools.py` implements the agentic loop for both Anthropic Messages API and OpenAI Chat Completions API.
- Max tool calls per run: 50 (configurable via `AGENT_MAX_TURNS` env var).
- `write_file` is sandboxed: only writes `vllm-qwen.yaml` or `Makefile` to the isolated per-run experiment directory (`results/sweep-NAME/TIMESTAMP/runllm/`). It never touches the shared project `runllm/`.
- Web search uses Exa API (`EXA_API_KEY`). Falls back to DuckDuckGo HTML scraping if the key is unset. The key is read from the environment or `.env` file.

### Run Retros

- Every run (success or failure) writes a `RETRO.md` via `_write_run_retro()` in `ai_experiment.py`.
- The retro agent gets up to 10 tool calls to inspect logs and gather evidence.
- Retros are designed for consumption by future AI agents. They capture: exact knob changes, key metrics or errors, causal explanations, crashes from any phase, research findings, and non-obvious pitfalls.
- Retros should be terse (3-10 lines) but complete.

### Benchmark / Retry Flow

- `ai_experiment.py` uses up to 10 internal attempts per improve run.
- A retry can return `NO_CONFIG_CHANGE`, which currently means “rerun benchmark with the same YAML” rather than “stop immediately”.
- Benchmark output is more verbose now:
  - live `guidellm` output is streamed into the terminal
  - stalled runs print periodic waiting messages with the last harness line
- The old 180s generic abort no longer kills benchmarks that are still making request progress.

### Pod Management

- Improve runs use unique pod names like `vllm-qwen-<timestamp_suffix>`.
- Pods are labeled for sweep discovery:
  - `autollm-managed: "true"`
  - `autollm-sweep: "<sweep-name>"`
- Pod cleanup happens on success, failure, and normal signal exit.
- `make sweep-pods` depends on those labels.

### runllm Surface

- `autollm/runllm` is the only `runllm` copy that should matter here.
- The top-level sibling `../runllm` was intentionally removed.
- `runllm/query.py` and `runllm/test_smoke.sh` use `/v1/chat/completions`.
- `runllm/Makefile` respects exported `KUBECONFIG` and otherwise falls back to `../kubeconfig`.

---

## Known Gotchas

1. **Kubernetes label values must be strings.**
   `autollm-managed: true` breaks `kubectl apply` with `cannot unmarshal bool into ... labels of type string`. The label injection code in `ai_experiment.py` now quotes values explicitly.

2. **Do not claim a fix works without testing it.**
   There is a workspace rule enforcing this, and this codebase has several harness-vs-config failure modes that are easy to misdiagnose.

3. **Be careful with submodule vs repo boundaries.**
   `autollm/runllm` is a git submodule. If you change it, commit inside the submodule first, then commit the updated submodule pointer in `autollm`.

4. **`results/` should not be tracked by git.**
   `autollm/.gitignore` now ignores `results/` and `results.txt`. Generated sweep and benchmark output should stay local.

5. **Prompt contract changes are high leverage.**
   Small wording changes in `ai_experiment.py` can materially change agent behavior. Be deliberate.

---

## Validation Shortlist

When changing this area, the cheap checks that have been useful are:

```bash
python3 -m py_compile scripts/ai_experiment.py scripts/agent_tools.py scripts/benchmark_config.py scripts/benchmark_harness.py scripts/run_guideline_experiment.py scripts/start_sweep.py scripts/sweep_utils.py scripts/list_sweep_pods.py
python3 scripts/test_sweep_setup.py
env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --refresh-leaderboard --sweep qwen-throughput
```

For `runllm` changes:

```bash
bash -n runllm/test_smoke.sh
python3 -m py_compile runllm/query.py
```

---

## If You Add Durable Knowledge

If you discover something about the real architecture, contracts, failure modes, or operational pitfalls that future agents are likely to trip over again, add it here briefly. Keep this file focused on stable, high-value context rather than transient run results.
