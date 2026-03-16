# autollm

AI-driven vLLM optimization on Kubernetes. Deploys vLLM, benchmarks latency/throughput, and uses an AI agent to iteratively improve the config.

**Requires:** Kubernetes cluster with GPU nodes.

## Setup

```bash
git clone --recurse-submodules https://github.com/lukas/autollm
cd autollm

# 1. Bootstrap local deps + kubeconfig:
make setup

# Or do the setup steps manually:
cp .env.example .env           # fill in KUBECONFIG_SERVER + KUBECONFIG_TOKEN
make kubeconfig                 # generates kubeconfig
# OR: copy your kubeconfig directly to ./kubeconfig

# 2. Set your AI API key in .env:
# ANTHROPIC_API_KEY=sk-...   # default provider
# OPENAI_API_KEY=sk-...      # for AI_PROVIDER=openai

# 3. Start a sweep (deploys vLLM, runs baseline benchmark):
make sweep SWEEP=qwen-latency GOAL="minimize latency"

# 4. Let the AI agent optimize:
make improve SWEEP=qwen-latency

# Or use GPT:
AI_PROVIDER=openai AI_MODEL=gpt-5.4 make improve SWEEP=qwen-latency
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

Kimi-specific note: `runllm/kimi/` currently uses HuggingFace safetensors cached on the shared PVC plus `--trust-remote-code`, not tensorizer. Startup is therefore slower than the tensorized Qwen paths, but baseline and improve runs now work end-to-end.

### Step 2: Run AI-driven improvements

```bash
make improve SWEEP=qwen-latency                        # single improvement run
make improve SWEEP=qwen-latency RUNS=10                # run 10 iterations back-to-back
make improve SWEEP=qwen-latency RUNS=5 ALLOW_MODEL_CHANGE=1  # 5 runs, allow quantized models
AI_PROVIDER=openai AI_MODEL=gpt-5.4 make improve SWEEP=qwen-latency RUNS=10
```

Each run:
1. Shows the agent the current best config + leaderboard + retros from past runs
2. Agent uses tools (web search, file reading, kubectl, log inspection) to research and propose a change
3. Agent writes the config via `write_file`, deploys, and benchmarks
4. If it crashes or stalls, retries up to 3 times with the agent diagnosing via logs/kubectl
5. After every run (success or failure), the agent writes a `RUN_RETRO.md` capturing what changed, what happened, and lessons for future agents

Sweep-local agent memory:
- External research is now persisted per sweep in `RESEARCH_LOG.md`.
- A compact cached synthesis is written to `RESEARCH_MEMORY.md` and included in later improve prompts.
- The agent is expected to read that research memory before doing more web search, so web research can be more thorough without redoing the same searches every run.
- If a run fails because the pod is unschedulable (for example `Insufficient nvidia.com/gpu`), the improve loop now treats that as a cluster-capacity stop condition instead of wasting retries "repairing" the YAML.

Sweep safety rails:
- The sweep stops automatically after 10 failed runs in a row.
- The sweep also stops after 2 consecutive failures classified as unfixable, such as provider/tool credit exhaustion, auth failures, Exa quota failures, or repeated timeout failures.
- Each sweep directory maintains an `OVERVIEW.md` with the started time, benchmark/data config, agent provider/model, tracked `runllm/` directories, current run counts, and failure-streak status.

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
Web research calls default to 20 per run (configurable via `AGENT_MAX_WEB_TOOL_CALLS`), but prior research is cached per sweep so later runs can usually reuse what was already learned.
Agent conversations and tool calls are recorded locally in per-run `agent.log` files plus the sweep-level `agent.log`; there is no built-in external tracing backend.

### Run retros

Every run produces a `RUN_RETRO.md` in its run directory. Retros are written by the agent after benchmarking and are designed to be read by future agents. They capture:
- Exact knob changes and their values
- Key metrics or the specific error
- Causal explanation of why the change worked or failed
- Crashes or errors from any phase (deploy, runtime, benchmark)
- Research findings discovered during the run (version-specific behavior, undocumented defaults, flag interactions)
- Non-obvious pitfalls for future experiments

Each sweep also keeps a higher-level synthesis in both `FULL_RETRO.md` and `FULL_RETRO.txt` at the sweep root. When a new run starts, the current full-retro snapshot is copied into that run directory too, so you can see exactly what cross-run memory the agent had at that point in time.

### What the agent can tune

- **vLLM args:** dtype, max-model-len, gpu-memory-utilization, max-num-batched-tokens, max-num-seqs, chunked-prefill, prefix-caching, enforce-eager, kv-cache-dtype, etc.
- **Speculative decoding:** draft model + num_speculative_tokens via `--speculative-config`
- **Compilation:** `--compilation-config '{"mode": 3}'`, `--performance-mode interactivity`
- **Environment variables:** VLLM_ATTENTION_BACKEND, VLLM_LOGGING_LEVEL, etc.
- **Quantized models** (with `ALLOW_MODEL_CHANGE=1`): AWQ, GPTQ-Int4/Int8 variants

### Benchmark presets

| Preset | Profile | Requests | Time limit | Rate | Data | Use case |
|--------|---------|----------|------------|------|------|----------|
| `quick` | synchronous | 5 | 30s | — | 64+64 tokens | Fast iteration (~30s) |
| `sync` | synchronous | 20 | 60s | — | 64+64 tokens | Moderate (~1 min) |
| `sweep` | sweep | — | 60s | — | 256+128 tokens | Multi-profile |
| `medium` | synchronous | 200 | 300s | — | 256+128 tokens | Thorough (~2–5 min) |
| `medium-throughput` | concurrent | 200 | 300s | 64 | 256+128 tokens | Throughput-focused (~3 min) |
| `large` | concurrent | 500 | 600s | 64 | 256+128 tokens | Thorough throughput (~10 min) |
| `long` | synchronous | 1000 | 600s | — | 256+128 tokens | Comprehensive (~10 min) |

`--max-requests` has no hard limit — set `MAX_REQUESTS=2000` for even longer runs.

### Sweep directory structure

```
results/sweep-qwen-latency/
  sweep_metadata.json      # benchmark preset, created_at
  OVERVIEW.md              # sweep summary: workload, agent model, runllm variants, streak status
  baseline/                # baseline run
  leaderboard.txt          # ranked runs + failed strategies
  FULL_RETRO.md            # current sweep-wide retro synthesis (markdown)
  FULL_RETRO.txt           # legacy mirror of the same sweep-wide retro
  RESEARCH_LOG.md          # append-only log of sweep web research
  RESEARCH_MEMORY.md       # cached synthesized research findings reused by later runs
  best-runllm -> .../runllm  # symlink to best config's runllm
  results.txt              # experiment log
  agent.log                # full local agent conversation history (all runs)
  20260311_120000/          # improvement run
    runllm/                 # modified runllm snapshot
    vllm_config.yaml        # vLLM config used
    benchmarks.json         # benchmark results
    FULL_RETRO.md           # full sweep retro snapshot as seen by this run
    FULL_RETRO.txt          # legacy mirror of that snapshot
    RUN_RETRO.md            # agent-written retrospective (every run)
    agent.log               # agent conversation for this run
    deploy.log, kubectl_logs.txt, run.log, ...
```

### Remote sweep (runs in-cluster)

For long sweeps, run the agent inside the Kubernetes cluster so it survives laptop disconnects:

```bash
# Start remote sweep (creates a lightweight controller pod, syncs code, runs in background)
make sweep-remote SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b BENCHMARK=large RUNS=100 GOAL="maximize throughput"

# Continue a local sweep remotely (syncs local results to controller, runs improve in-cluster)
make improve-remote SWEEP=qwen-throughput-async RUNS=20

# Monitor
make sweep-logs                                # tail live output
make sweep-status                              # check running sweeps

# Pull results to local machine
make sync-results SWEEP=qwen3-235b-throughput  # incremental sync for one sweep
make sync-results                              # sync all results

# Cleanup
make sweep-remote-teardown                     # delete controller pod (sync first!)
```

The controller pod (`autollm-controller`) runs on a CPU node with a ServiceAccount that has RBAC permissions to manage vLLM pods. API keys plus `AI_PROVIDER` / `AI_MODEL` are injected from your local `.env` and environment, so remote sweeps can be pinned to GPT the same way as local runs.

`make sync-results SWEEP=...` is incremental: it always refreshes top-level sweep files such as `OVERVIEW.md`, `leaderboard.txt`, `FULL_RETRO.md`, `FULL_RETRO.txt`, `RESEARCH_MEMORY.md`, and `results.txt`, pulls any run directories that do not exist locally yet, and re-syncs the newest two run directories so active runs keep updating without re-copying the whole sweep every time. Sync also tolerates files changing while a live sweep is still writing logs or benchmark outputs.
If the controller pod is already gone, `make sync-results` now prints a friendly "nothing to sync" message and exits successfully.

Remote sweep bookkeeping notes:
- `make sweep-status` now ignores zombie controller-side shell PIDs and cleans stale `.pid` files automatically, so finished sweeps no longer appear stuck in `RUNNING`.
- Remote sweep launchers remove their own `.pid` files on normal exit and write `/workspace/sweep-<name>.exit_code` on the controller for postmortem inspection.
- The controller pod spec now uses a lightweight reaper loop instead of `sleep infinity`, but that change only takes effect after the controller pod is recreated. If you update the controller while long sweeps are in flight, wait for them to finish before running `make sweep-remote-teardown`.

## Other targets

| Target | Description |
|--------|-------------|
| `make setup` | One-time bootstrap: install deps and generate kubeconfig if needed |
| `make sweep SWEEP=name` | Create sweep + run baseline |
| `make improve SWEEP=name` | AI agent suggests improvements |
| `make full-sweep SWEEP=name RUNS=N` | Create sweep + baseline + N improvement runs |
| `make sweep-remote SWEEP=name RUNS=N` | Run full sweep on a K8s controller pod |
| `make improve-remote SWEEP=name RUNS=N` | Continue a local sweep remotely (sync results + improve) |
| `make sync-results SWEEP=name` | Incrementally sync one remote sweep to local |
| `make sweep-logs` | Tail live remote sweep output |
| `make sweep-status` | Check remote sweep status |
| `make sweep-remote-teardown` | Delete the controller pod |
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
| `AI_MODEL` | Default: `claude-opus-4-6`. Override: `gpt-5.4`, `gpt-5-codex`, etc. |
| `ALLOW_MODEL_CHANGE` | Set to `1` to let agent try quantized model variants |
| `GOAL` | Optimization goal for the agent (e.g. "minimize latency", "maximize throughput") |
| `BENCHMARK` | Preset: `quick`, `sync`, `sweep`, `medium`, `medium-throughput`, `large`, `long` |
| `MAX_REQUESTS` | Override max requests (no limit) |
| `MAX_SECONDS` | Override max benchmark duration |
| `EXA_API_KEY` | Exa API key for web search (falls back to DuckDuckGo if unset) |
| `AGENT_MAX_TURNS` | Max tool calls per agent run (default: 50) |
| `AGENT_MAX_WEB_TOOL_CALLS` | Max `search_web` / `fetch_url` calls per run (default: 20) |
| `SWEEP_MAX_CONSECUTIVE_FAILURES` | Stop a sweep after this many failed runs in a row (default: 10) |
| `SWEEP_MAX_CONSECUTIVE_UNFIXABLE_FAILURES` | Stop a sweep after this many unfixable failures in a row (default: 2) |
