# autollm

AI-driven vLLM optimization on Kubernetes. Deploys vLLM, benchmarks latency/throughput, and uses an AI agent to iteratively improve the config.

**Requires:** [runllm](runllm/) submodule + Kubernetes cluster with GPU nodes.

## Setup

```bash
git clone --recurse-submodules https://github.com/lukas/autollm
cd autollm

# 1. Configure cluster access (pick one):
cp .env.example .env           # fill in KUBECONFIG_SERVER + KUBECONFIG_TOKEN
make kubeconfig                 # generates autollm/kubeconfig
# OR: copy your kubeconfig directly to autollm/kubeconfig

# 2. Set your AI API key in .env:
# ANTHROPIC_API_KEY=sk-...

# 3. Start a sweep (deploys vLLM, runs baseline benchmark):
make sweep SWEEP=qwen-latency GOAL="minimize latency"

# 4. Let the AI agent optimize:
make improve SWEEP=qwen-latency
```

## Workflow: sweep + improve

### Step 1: Create a sweep with a baseline

```bash
make sweep SWEEP=qwen-latency GOAL="minimize latency"
make sweep SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b GOAL="maximize throughput"
make sweep SWEEP=qwen-ttft GOAL="minimize time to first token (TTFT)"
make sweep SWEEP=qwen-latency GOAL="minimize latency" BENCHMARK=medium  # 200 req, ~5 min
```

The `GOAL` tells the AI agent what metric to optimize. `MODEL_DIR` selects which model config from `runllm/` to use (default: `qwen2.5-1.5b`). Both are saved in `sweep_metadata.json` and included in every agent prompt for this sweep.

This deploys vLLM with the chosen model's `vllm-config.yaml`, runs the benchmark, and saves results to the sweep's `baseline/` directory.

### Step 2: Run AI-driven improvements

```bash
make improve SWEEP=qwen-latency                        # single improvement run
make improve SWEEP=qwen-latency RUNS=10                # run 10 iterations back-to-back
make improve SWEEP=qwen-latency RUNS=5 ALLOW_MODEL_CHANGE=1  # 5 runs, allow quantized models
```

Each run:
1. Shows the agent the current best config + leaderboard + retros from past runs
2. Agent uses tools (web search, file reading, kubectl, log inspection) to research and propose a change
3. Agent writes the config via `write_file`, deploys, and benchmarks
4. If it crashes or stalls, retries up to 10 times with the agent diagnosing via logs/kubectl
5. After every run (success or failure), the agent writes a `RETRO.md` capturing what changed, what happened, and lessons for future agents

Run `make improve` repeatedly to iterate. The agent always builds on the best config so far.

### Agent tool stack

The agent has access to these tools during each run:

| Tool | Description |
|------|-------------|
| `search_web` | Web search via Exa API (falls back to DuckDuckGo) |
| `fetch_url` | Fetch and extract content from a URL |
| `read_file` | Read project files (results/, runllm/, docs/, scripts/) |
| `write_file` | Write `vllm-config.yaml` or `Makefile` to the isolated per-run experiment directory only |
| `list_files` | List files in a project directory |
| `run_shell` | Run a shell command (read-only, no destructive ops) |
| `run_benchmark` | Deploy the written config and run the benchmark |
| `read_logs` | Read deploy, benchmark, or kubectl logs for a run |
| `kubectl_get` | Run `kubectl get` queries against the cluster |
| `kubectl_logs` | Fetch pod logs from the cluster |

The tool stack works with both Anthropic and OpenAI APIs. Max tool calls per run defaults to 50 (configurable via `AGENT_MAX_TURNS`).

### Run retros

Every run produces a `RETRO.md` in its run directory. Retros are written by the agent after benchmarking and are designed to be read by future agents. They capture:
- Exact knob changes and their values
- Key metrics or the specific error
- Causal explanation of why the change worked or failed
- Crashes or errors from any phase (deploy, runtime, benchmark)
- Research findings discovered during the run (version-specific behavior, undocumented defaults, flag interactions)
- Non-obvious pitfalls for future experiments

### What the agent can tune

- **vLLM args:** dtype, max-model-len, gpu-memory-utilization, max-num-batched-tokens, max-num-seqs, chunked-prefill, prefix-caching, enforce-eager, kv-cache-dtype, etc.
- **Speculative decoding:** draft model + num_speculative_tokens via `--speculative-config`
- **Compilation:** `--compilation-config '{"mode": 3}'`, `--performance-mode interactivity`
- **Environment variables:** VLLM_ATTENTION_BACKEND, VLLM_LOGGING_LEVEL, etc.
- **Quantized models** (with `ALLOW_MODEL_CHANGE=1`): AWQ, GPTQ-Int4/Int8 variants

### Benchmark presets

| Preset | Profile | Requests | Time limit | Data | Use case |
|--------|---------|----------|------------|------|----------|
| `quick` | synchronous | 5 | 30s | 64 prompt + 64 output tokens | Fast iteration (~30s) |
| `sync` | synchronous | 20 | 60s | 64 prompt + 64 output tokens | Moderate (~1 min) |
| `sweep` | sweep (multiple profiles) | — | 60s | 256 prompt + 128 output tokens | Multi-profile |
| `medium` | synchronous | 200 | 300s | 256 prompt + 128 output tokens | Thorough (~2–5 min) |
| `long` | synchronous | 1000 | 600s | 256 prompt + 128 output tokens | Comprehensive (~10 min) |

`--max-requests` has no hard limit — set `MAX_REQUESTS=2000` for even longer runs.

### Sweep directory structure

```
results/sweep-qwen-latency/
  sweep_metadata.json      # benchmark preset, created_at
  baseline/                # baseline run
  leaderboard.txt          # ranked runs + failed strategies
  best-runllm -> .../runllm  # symlink to best config's runllm
  results.txt              # experiment log
  agent.log                # full agent conversation history (all runs)
  20260311_120000/          # improvement run
    runllm/                 # modified runllm snapshot
    vllm_config.yaml        # vLLM config used
    benchmarks.json         # benchmark results
    RETRO.md                # agent-written retrospective (every run)
    agent.log               # agent conversation for this run
    deploy.log, kubectl_logs.txt, run.log, ...
```

## Other targets

| Target | Description |
|--------|-------------|
| `make sweep SWEEP=name` | Create sweep + run baseline |
| `make improve SWEEP=name` | AI agent suggests improvements |
| `make benchmark` | One-shot benchmark (deploy + bench, saves to results/runs/) |
| `make benchmark BENCHMARK=quick` | Quick one-shot benchmark |
| `make experiment` | Standalone AI experiment (no sweep) |
| `make leaderboard SWEEP=name` | Refresh `results/sweep-name/leaderboard.txt` |
| `make sweep-pods SWEEP=name` | List running labeled pods for a sweep |
| `make dashboard` | Web dashboard at http://localhost:8765/ |
| `make query PROMPT="Hello"` | Send a query to running vLLM |

## Environment variables

| Variable | Description |
|----------|-------------|
| `KUBECONFIG` | Cluster access — copy to `autollm/kubeconfig`, export it, or generate with `make kubeconfig` |
| `ANTHROPIC_API_KEY` | Required for AI agent (default provider) |
| `OPENAI_API_KEY` | For OpenAI provider |
| `AI_PROVIDER` | `anthropic` (default) or `openai` |
| `AI_MODEL` | Default: `claude-opus-4-6`. Override: `gpt-5-codex`, etc. |
| `ALLOW_MODEL_CHANGE` | Set to `1` to let agent try quantized model variants |
| `GOAL` | Optimization goal for the agent (e.g. "minimize latency", "maximize throughput") |
| `BENCHMARK` | Preset: `quick`, `sync`, `sweep`, `medium`, `long` |
| `MAX_REQUESTS` | Override max requests (no limit) |
| `MAX_SECONDS` | Override max benchmark duration |
| `EXA_API_KEY` | Exa API key for web search (falls back to DuckDuckGo if unset) |
| `AGENT_MAX_TURNS` | Max tool calls per agent run (default: 50) |
