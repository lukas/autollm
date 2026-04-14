# Agent Handoff: autollm Sweep Workflow

**Purpose:** durable context for future agents working on `autollm`. Read this before changing sweep/improve behavior, benchmark flow, or `runllm` integration.

---

## Current Primary Workflow

The main path is the sweep workflow, not the older dashboard optimizer:

```bash
make sweep SWEEP=qwen-latency RUNS=10 MODEL=qwen2.5-1.5b GOAL="minimize latency"
make sweep SWEEP=qwen3-235b-throughput RUNS=20 MODEL=qwen3-235b GOAL="maximize throughput"
make sync-results SWEEP=qwen-latency
make improve-remote SWEEP=qwen-latency RUNS=10
make leaderboard SWEEP=qwen-latency
make sweep-pods SWEEP=qwen-latency
```

- `make sweep` is now the primary controller-backed full-sweep command. It creates the remote sweep, runs the baseline there, then performs `RUNS` improve iterations in-cluster.
- `make baseline` is the explicit baseline-only step when you want to create local sweep metadata and run just the baseline.
- `make sweep-local` is the local baseline + improve wrapper. `make improve` remains the local continue-an-existing-sweep command.
- `make improve` runs `scripts/ai_experiment.py`, which copies the current best `runllm`, prompts the LLM, deploys a unique pod, runs a sample query, benchmarks it, and updates the sweep artifacts.
- `make leaderboard` refreshes `results/sweep-NAME/leaderboard.txt`.
- `make sweep-pods` lists currently running pods labeled for a sweep.

### Remote sweep (agent runs in-cluster)

```bash
make sweep SWEEP=qwen-throughput-async MODEL=qwen2.5-1.5b BENCHMARK=medium-throughput RUNS=30 GOAL="maximize throughput"
make sweep-logs                            # tail live output
make sweep-status                          # check running sweeps
make sync-results SWEEP=qwen-throughput-async  # copy results to local machine
make sweep-remote-teardown                 # delete controller pod
```

- `make sweep` creates a lightweight controller pod (`autollm-controller`) in the cluster, syncs local code to it, and starts the sweep in the background. The controller uses a ServiceAccount with RBAC permissions to manage vLLM pods. API keys plus `AI_PROVIDER` / `AI_MODEL` come from `.env` or the local environment.
- The sweep runs autonomously inside the pod (survives laptop disconnect). Results stay on the controller.
- `make sync-results` uses tar+kubectl to pull results back. Syncs a specific sweep or all results.
- `make sync-results` must tolerate files changing during active sweeps. `scripts/sweep_remote.sh` now uses `tar --ignore-failed-read --warning=no-file-changed` on the controller side so live `benchmark_live.txt` / `benchmarks.json` updates do not corrupt the sync stream.
- `make sync-results SWEEP=...` is now incremental: it refreshes top-level sweep files (`OVERVIEW.md`, `leaderboard.txt`, `FULL_RETRO.md`, `RESEARCH_MEMORY.md`, etc.), always syncs `baseline/`, pulls missing timestamped run dirs, and re-syncs the newest two run dirs. Keep the shell compatible with macOS Bash 3.2; avoid `mapfile` and associative arrays.
- If the remote controller pod no longer exists, `make sync-results` now prints a friendly "nothing to sync" message and exits successfully instead of failing the Make target.
- `make setup` is now the explicit bootstrap step for a fresh checkout (`uv sync` + conditional kubeconfig generation). Common dev targets like `make benchmark`, `make baseline`, `make sweep`, `make improve`, and `make experiment` no longer auto-run `uv sync` first.
- Remote sweep launcher scripts now run through a tiny wrapper that removes `/workspace/sweep-<name>.pid` on exit and writes `/workspace/sweep-<name>.exit_code`. `make sweep-status` also ignores zombie PIDs and cleans stale pid files, since finished background shells can otherwise remain as `<defunct>` under the controller pod.
- The controller pod itself should stay on the reaper loop in `sweep-controller.yaml` rather than `sleep infinity`; otherwise orphaned background sweep shells become zombie processes under PID 1.

The older `scripts/ai_benchmark_optimizer.py` / dashboard flow still exists, but it is no longer the main tuning workflow.

---

## Important Files

| Path | Purpose |
|------|---------|
| `scripts/ai_experiment.py` | Main sweep improve loop, prompt construction, deploy/benchmark, retries, retro writing, cleanup |
| `scripts/agent_tools.py` | Tool definitions, execution engine, and provider-agnostic agent loop (Anthropic + OpenAI) |
| `scripts/benchmark_config.py` | Shared benchmark presets and Guideline progress parsing helpers |
| `scripts/benchmark_harness.py` | One-shot benchmark harness for `results/runs/` |
| `scripts/k8s_benchmark.py` | Shared K8s Job runner for guidellm benchmarks (replaces local guidellm execution) |
| `scripts/vllm_profiling.py` | Shared helpers for periodic vLLM `/metrics` sampling, best-effort GPU sampling, and hardware profile summaries |
| `scripts/run_guideline_experiment.py` | Guideline K8s Job wrapper for experiment mode; writes `query_progress.json` |
| `scripts/start_sweep.py` | Baseline sweep creation |
| `scripts/sweep_utils.py` | Best-run scoring and objective helpers |
| `scripts/sweep_remote.sh` | Remote sweep orchestration: create controller pod, sync code, start sweep, sync results |
| `sweep-controller.yaml` | Controller pod spec (python:3.13-slim + kubectl + uv, ServiceAccount for pod management) |
| `sweep-controller-rbac.yaml` | RBAC: ServiceAccount, Role, RoleBinding for controller to manage vLLM pods |
| `runllm/<model>/` | Per-model vLLM deploy/query/test directories (e.g. `qwen2.5-1.5b/`, `qwen3-235b/`, `kimi-vllm/`, `kimi-trt/`). Each has `pod.yaml`, `Makefile`, `query.py`, `test_smoke.sh`. |
| `docs/BENCHMARK_HARNESS.md` | Current harness and sweep docs |
| `docs/PROFILING_GUIDE.md` | How to profile latency-by-length + nsys GPU kernels; decision trees for what to optimize |
| `scripts/profile_model.py` | Standalone profiling script: latency sweep + nsys kernel breakdown against any running pod |
| `docs/SWEEP_BEST_PRACTICES.md` | One-page synthesis of cross-sweep lessons for future optimization agents |
| `results/sweep-NAME/AGENT_CONTEXT.md` | Generated compact sweep memory for prompts: top frontier, repeated failures, and harness-only patterns |
| `results/sweep-NAME/RESEARCH_LOG.md` | Append-only log of external research (`search_web` / `fetch_url`) done during the sweep |
| `results/sweep-NAME/RESEARCH_MEMORY.md` | Cached synthesized research memory that future runs should read before doing more web research |

**Nested repo:** `grist/` is gitignored here; it is its own project at [github.com/lukas/grist](https://github.com/lukas/grist). Clone into `./grist` beside this tree if needed. Current Grist builds include a restored Claude/Cursor-style skill system with bundled skills, a Skills modal, global/project install roots at `~/.grist/skills/` and `<repo>/.grist/skills/`, a typed manager-worker swarm contract (`manager`, `scout`, `implementer`, `reviewer`, `verifier`, `summarizer`) with structured artifacts and an `AGENTS.md` repo contract, git-first bootstrap with local per-agent branches/worktrees, selective best-effort Docker runtimes with persisted port/runtime metadata and cleanup, a stricter greenfield path that drops empty-repo scouts, keeps one main implementer, and bumps that implementer's step budget, command execution that now resolves relative `cwd` values inside the task worktree instead of the Grist repo, adaptive verifier checks that stop after the first hard failure and can use build/startup smoke when `npm test` is absent, reducer gating that keeps summarizers blocked until non-reducer work is finished and dependency artifacts exist, safer shell-command chaining that only permits individually allowlisted segments, a more forgiving internal `apply_patch` tool (`diff` or `patch` input), automatic verifier-driven repair tasks on the same worktree, one post-verify wrap-up implementer for cleanup/docs/PR/memory work, verified source-file apply-back into the canonical repo, verifier-gated completion so runs do not finish while the latest relevant verifier is still failing, softer verifier/summarizer failure recovery after successful implementation, a calmer task feed that collapses patch-heavy tool output into compact diff summaries, viewport-level blocker tooltips so hover text is not clipped by the scrollable sidebar, single-instance Electron startup, a shareable `docs/SWARM_STRATEGY_SUMMARY.md` review doc, and a clean shutdown path that stops scheduler timers before closing SQLite. `task_diff` rows stay compact by default and expand into a single focused diff panel instead of showing metadata/debug structure.

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
  - per-run timing breakdown: agent thinking time, deploy (pod spin-up) time, benchmark time, and total wall time
- Improve prompts now use a compact context window by default: top successful runs, the most recent failed runs, a short structured sweep-memory block, the newest `RUN_RETRO.md`, and a cached `FULL_RETRO.md` synthesis instead of dumping the full sweep state every run.
- `results/sweep-NAME/AGENT_CONTEXT.md` is regenerated alongside `leaderboard.txt` as a deterministic cache for future agents/humans. It summarizes the current frontier plus repeated failure classes and harness-only patterns.
- `FULL_RETRO.md` is the canonical sweep-level retro synthesis. The synthesis is cached and only regenerated when the sweep meaningfully changes (for example a new best run, new failure class, or updated retro content), which cuts repeated prompt cost.
- Web research is now sweep-local and durable: `search_web` / `fetch_url` append to `RESEARCH_LOG.md`, and `RESEARCH_MEMORY.md` is a cached synthesis of that history. Improve prompts include the research memory so later runs can reuse prior web work instead of re-searching.
- Prompt guidance pushes the agent toward single-change experiments and allows `NO_CONFIG_CHANGE: ...` on retries when logs suggest a harness/watchdog issue rather than a config issue.

### Tool-Calling Agent

- The agent now uses a full tool stack defined in `scripts/agent_tools.py` (10 tools: `search_web`, `fetch_url`, `read_file`, `write_file`, `list_files`, `run_shell`, `run_benchmark`, `read_logs`, `kubectl_get`, `kubectl_logs`).
- `run_agent()` in `agent_tools.py` implements the agentic loop for both Anthropic Messages API and OpenAI Responses API.
- Both API loops use exponential-backoff retry (up to 5 attempts, 15s–300s delay) for transient errors (HTTP 500, 502, 503, 529, rate limits). This prevents API outages from burning through sweep runs.
- OpenAI improve runs now use the Responses API in `scripts/agent_tools.py`, so GPT-5-class models can do tool calling without falling back to older chat-completions-only models. User preference in this workspace is GPT-5.4/latest GPT or latest Anthropic only; do not silently downgrade to `gpt-4o`/`gpt-4o-mini`.
- Max tool calls per run: 50 (configurable via `AGENT_MAX_TURNS` env var). When the agent writes custom code files, the budget is automatically boosted by `AGENT_CUSTOM_CODE_BUDGET_BOOST` (default 100).
- Conversation/tool traces are stored locally in `agent.log` files; there is no required external tracing dependency in the current workflow.
- `write_file` is sandboxed to the isolated per-run experiment directory (`results/sweep-NAME/TIMESTAMP/runllm/`). It never touches the shared project `runllm/`. Allowed files: `pod.yaml`, `Makefile`, and custom code files with extensions `.py`, `.sh`, `.json`, `.patch`, `.cfg`, `.toml`, `.txt`.
- Web search uses Exa API (`EXA_API_KEY`). Falls back to DuckDuckGo HTML scraping if the key is unset. The key is read from the environment or `.env` file.
- Web tools now keep sweep-local memory. Agents are expected to read sweep research memory first, then use web calls only to fill genuine gaps rather than rediscovering the same facts every run. The default per-run web-call budget is now 20 via `AGENT_MAX_WEB_TOOL_CALLS`.

### Custom Code Files (ConfigMap Mounting)

- The agent can write custom code files (`.py`, `.sh`, etc.) to the experiment directory alongside `pod.yaml`.
- Before deploying, `_deploy_and_benchmark()` in `ai_experiment.py` automatically:
  1. Scans the experiment directory for files with extensions in `PATCHES_CONFIGMAP_EXTENSIONS`.
  2. Creates a K8s ConfigMap (`<pod-name>-patches`) from those files.
  3. Injects a `volumes` entry and `volumeMounts` entry into the pod spec via YAML manipulation.
  4. Files become available inside the pod at `/workspace/patches/<filename>` (read-only).
- The pod's startup script (in `pod.yaml` `args`) should copy or apply patches from `/workspace/patches/`.
- ConfigMaps are cleaned up automatically when the pod is deleted.
- Custom code files **persist across runs**: `shutil.copytree` copies all files from the best run's `runllm/` dir to the next run's experiment dir, so custom code accumulates and evolves.
- The agent prompt tells the agent about inherited custom code files and how to use them.
- ConfigMap size limit: 1MB (K8s hard limit). This is sufficient for monkey-patches and custom modules but not for large binary data.
- This enables optimizations beyond config tuning: custom speculative decoders, patched scheduling logic, custom kernels, etc.

### Run Retros

- Every run (success or failure) writes a `RUN_RETRO.md` via `_write_run_retro()` in `ai_experiment.py`.
- The retro agent gets up to 10 tool calls to inspect logs and gather evidence.
- Retros are designed for consumption by future AI agents. They capture: exact knob changes, key metrics or errors, causal explanations, crashes from any phase, research findings, and non-obvious pitfalls.
- Run retros should be concise but evidence-rich, with exact values and benchmark/profile facts whenever available.
- If a single run directory contains multiple internal attempts, new retros are appended to `RUN_RETRO.md` with a markdown separator instead of overwriting the previous attempt.
- When a run starts, the current `FULL_RETRO.md` snapshot is copied into that run directory so you can reconstruct exactly what sweep memory the agent saw at that time.
- New improve prompts include both the newest per-run `RUN_RETRO.md` in the sweep and the synthesized `FULL_RETRO.md`, so the next agent sees the freshest local context plus the higher-level summary.

### In-Cluster Benchmarking (K8s Jobs)

- **guidellm runs as a K8s Job inside the cluster**, not locally on macOS. This was changed because guidellm 0.5.3's multiprocessing deadlocks on macOS for anything beyond trivial benchmarks, and `kubectl port-forward` is unreliable for long runs.
- The shared module `scripts/k8s_benchmark.py` handles job creation, log streaming, result extraction, and cleanup.
- **Networking:** The benchmark Job gets the vLLM pod's cluster IP via `kubectl get pod -o jsonpath` and connects directly (e.g. `http://10.0.0.164:8000`). No port-forward, no Service object.
- **Image:** Uses `python:3.12-slim` by default. guidellm is installed into a persistent venv on the PVC (`/mnt/models/.cache/guidellm-venv`) so it's only installed once — subsequent benchmark Jobs reuse the cached venv. Set `GUIDELLM_BENCH_IMAGE` to a pre-built image to skip even the cache check.
- **Result extraction:** The Job dumps `benchmarks.json` to stdout via markers (`===BENCHMARKS_JSON_START===` / `===BENCHMARKS_JSON_END===`). The harness extracts JSON from the captured `kubectl logs` stream. This avoids `kubectl cp` which fails on completed pods.
- **Node placement:** Benchmark Job uses the same `nodeSelector` (`lukas-4h200-pool`) as the vLLM pod for network proximity, but requests 0 GPUs (CPU + 4GB RAM only).
- **Who calls it:**
  - `benchmark_harness.py` (baseline runs) calls `run_benchmark_k8s()` directly.
  - `ai_experiment.py` (improve runs) calls `run_benchmark_k8s()` directly in `_deploy_and_benchmark()`. Port-forward is no longer used.
  - `run_guideline_experiment.py` also uses `run_benchmark_k8s()` and expects `EXPERIMENT_POD_NAME` env var.
- If the serving config uses `--trust-remote-code`, the benchmark Job must pass `--processor-args '{"trust_remote_code": true}'` so guidellm can load the same tokenizer/processor path. This is required for Kimi-K2.5.

### Profiling (Latency-by-Length + nsys GPU Kernels)

`scripts/profile_model.py` is a standalone tool that profiles any running serving pod:

```bash
# Quick latency sweep (no nsys, ~2 min):
make profile POD=sglang-kimi-bench MODEL_NAME=moonshotai/Kimi-K2.5

# With nsys kernel profiling (pod must be started under nsys launch):
make profile POD=sglang-kimi-bench MODEL_NAME=moonshotai/Kimi-K2.5 NSYS=1 NSYS_SESSION=kimi_profile
```

Outputs in `results/profile-<pod>/`: `latency_table.txt` (compact table for agent context), `kernel_summary.txt` (GPU kernel breakdown by output length), `latency_vs_seqlen.png` (graph).

Agents can run this via `run_shell` before planning optimization strategies:
- Read `latency_table.txt` to understand how latency/throughput scales with sequence length
- Read `kernel_summary.txt` to identify whether the bottleneck is communication, attention, or compute
- See `docs/PROFILING_GUIDE.md` for the full decision tree

For nsys, the serving pod must be started with `nsys launch --session-new=<name> --trace=cuda,nvtx ...` wrapping the serve command. Set `restartPolicy: Never` during profiling.

### Auto-Collected GPU Topology & NCCL Transport

The first run of each sweep collects GPU interconnect info and caches it in `results/sweep-NAME/gpu_topology.json`. Subsequent runs skip collection entirely (~0ms overhead). Re-collected only if the pod lands on a different node.

Data collected:
- **`nvidia-smi topo -m`**: GPU topology matrix (NVLink, NVSwitch, PIX, SYS connections)
- **NCCL transport**: network type, bandwidth, channel counts, P2P transport, NVLS status, InfiniBand availability (only when pod has `NCCL_DEBUG=INFO`)
- **NVLink status**: active link count per GPU

A compact summary is automatically included in every improve prompt so the agent knows the interconnect. To get the full NCCL transport info (not just nvidia-smi topo), add these env vars to the pod spec:
```yaml
- name: NCCL_DEBUG
  value: "INFO"
- name: NCCL_DEBUG_SUBSYS
  value: "INIT,NET,GRAPH"
```

### Model-Specific Insights

`results/<model-family>-insights/` directories contain durable profiling and optimization knowledge for each model family. These are automatically loaded into improve prompts when the sweep's `model_family` matches.

| Directory | Contents |
|-----------|----------|
| `results/kimi-insights/` | Kimi-K2.5: kernel breakdown, latency profile, GPU topology, NVLS experiment, optimization strategy |

Each directory has:
- `SUMMARY.md` — consolidated summary (loaded into agent prompt, truncated to 3000 chars)
- Individual insight files (topology, kernel breakdown, latency, experiment results)

To add insights for a new model: create `results/<family>-insights/SUMMARY.md`. The `_get_model_insights()` function in `ai_experiment.py` loads it by matching on `model_family` from `sweep_metadata.json`.

### Deploy Watchdog (Activity-Aware Timeout)

The health check watchdog in `ai_experiment.py` uses an activity-aware strategy instead of a flat timer:
- **`INSPECT_AFTER_SEC` (180s default):** If no new deploy activity appears for this long during deploy/health phases, the run is aborted. Env var: `EXPERIMENT_INSPECT_AFTER_SEC`.
- **`DEPLOY_HARD_TIMEOUT` (600s default):** Absolute ceiling for deploy+health phases regardless of log activity. Env var: `EXPERIMENT_DEPLOY_HARD_TIMEOUT`.
- During `pod_wait`, the watchdog now also snapshots `kubectl get pod -o json` into `pod_status.jsonl`, treats observed pod lifecycle/status polling as activity, and surfaces fatal states like `Unschedulable`, `ImagePullBackOff`, or terminated containers before cleanup.
- During `health_check`, the watchdog tracks kubectl log file size. As long as vLLM is actively writing logs (loading weights, CUDA graph capture, fp8 scale calibration), the timeout keeps sliding forward. Only aborts when logs go stale.
- This allows large models (Qwen3-235B) and slow startup configs (fp8 KV cache calibration) to complete startup without hitting the watchdog, while still catching truly stuck deployments.
- `ai_experiment.py` now uses a config-aware hard timeout: Kimi-K2.5 gets 1800s by default because the HF safetensors fallback path can spend ~500s in weight loading before health becomes ready.

### Benchmark / Retry Flow

- `ai_experiment.py` uses up to 3 internal attempts per improve run.
- Improve runs are now intended to test one experiment hypothesis per run directory. Internal retries are for debugging that same experiment when the benchmark exposed a crash/startup/harness bug, not for pivoting to a new tuning idea.
- A retry can return `NO_CONFIG_CHANGE`, which now means “stop this run and let the next run/agent choose the next experiment”, not “rerun benchmark with the same YAML”.
- Whole sweeps now stop automatically after 10 failed runs in a row, or after 2 consecutive failures classified as unfixable (`credits`, `auth`, `exa`, or `timeout`). `scripts/ai_experiment.py` exits with code `40` when that policy trips, and both local `make improve` and remote controller loops stop on that code.
- Both `make improve` and `make benchmark` run a lightweight profiler during the benchmark:
  - samples vLLM `/metrics` every few seconds into `vllm_metrics_timeseries.jsonl`
  - writes a compact `vllm_metrics_profile.json` summary with queue/cache/throughput peaks and diagnosis hints
  - writes `hardware_context.json` with node placement and resource limits
  - writes `gpu_metrics_timeseries.jsonl` if `nvidia-smi` is available inside the pod
- If you are debugging a bad run, check `vllm_metrics_profile.json` before reading raw logs. It often tells you whether the failure was KV cache pressure, queue buildup, or low GPU utilization.
- A single improve run directory can contain multiple internal attempts. When reading a bad `RETRO.md`, verify the final outcome against `results.txt`, `benchmarks.json`, and the terminal output if the retro seems inconsistent.

### Pod Management

- Improve runs use unique pod names like `<base-pod-name>-<timestamp_suffix>`.
- The deploy helper strips any trailing prior run suffixes before appending the current one, so internal retries for the same run do not create names like `...-15173225-15173225`.
- Pods are labeled for sweep discovery:
  - `autollm-managed: "true"`
  - `autollm-sweep: "<sweep-name>"`
- On failed deploy/health/sample-query attempts, the harness captures `pod_get.json`, `pod_describe.txt`, `pod_events.txt`, and current/previous pod logs before deleting the pod.
- Pod cleanup happens on success, failure, and normal signal exit.
- Before deploying, `_deploy_and_benchmark` now deletes all stale pods labeled with the same `autollm-sweep` label. This prevents GPU exhaustion from orphaned pods created by earlier failed runs with mismatched names.
- `make sweep-pods` depends on those labels.

### runllm Surface

- `autollm/runllm/` contains per-model deployment variants (for example `qwen2.5-1.5b/`, `qwen3-235b/`, `kimi-vllm/`, `kimi-sglang/`, `kimi-sglang-eagle/`, `kimi-sglang-concurrent/`, `kimi-sglang-tensorizer/`).
- Each model dir is self-contained with `pod.yaml`, `Makefile`, `query.py`, `test_smoke.sh`.
- `query.py` and `test_smoke.sh` use `/v1/chat/completions`.
- Each Makefile respects exported `KUBECONFIG` and otherwise falls back to `../../kubeconfig` (relative to the model dir).
- `runllm/qwen2.5-1.5b-sglang/` is a sibling SGLang variant that intentionally keeps the same filenames and `VLLM_MODEL` Makefile variable for compatibility with the existing `runllm`/sweep directory contract.
- Sweeps now store `model_family`, `baseline_variant`, and `model_variants` in `sweep_metadata.json` so improve runs know the canonical family plus every deployment variant available to that sweep.
- Family-first sweep creation is now the default contract. For example, `make sweep MODEL=kimi` automatically exposes `kimi-vllm`, `kimi-sglang`, and `kimi-sglang-eagle`; use `BASELINE_VARIANT=kimi-sglang-eagle` to start the baseline on the EAGLE-3 speculative decoding variant.
- Backend switches should replace both `pod.yaml` and `Makefile` from the chosen canonical variant template.
- Every sweep directory now keeps an `OVERVIEW.md` with started time, benchmark/data config, agent provider/model, tracked `runllm/` variants, run counts, and current failure streak / stop-policy status. Refresh it whenever sweep metadata or run outcomes change.

### Tensorizer / PVC Model Loading

- Most large models use `--load-format tensorizer` with pre-serialized weights on a shared PVC (`models`, 5Ti, `shared-vast`). The PVC mounts at `/mnt/models/`. Serialized weights at `/mnt/models/vllm/<org>/<model>/v1/`.
- PVC definition: `runllm/models-pvc.yaml`.
- To serialize: `make tensorize MODEL_DIR=qwen2.5-1.5b` (K8s Job; idempotent — skips if marker file already exists on PVC).
- The nightly vllm image doesn't bundle tensorizer, so all configs use `command: ["/bin/bash", "-c"]` to `pip install tensorizer` before `vllm serve`.
- All configs use `--served-model-name <HF-name>` (e.g. `Qwen/Qwen2.5-1.5B-Instruct`) so the API model name matches what Makefiles and query scripts expect, even though the actual `--model` path points to the PVC.
- **Startup patches (applied at container init):** Two vllm bugs require runtime patching in the init script:
  1. **Patch-1 (vllm#25751):** `MetaTensorMode` only intercepts `aten::empty`, causing 2x GPU memory during deserialization. Fix: expand to 18 factory ops via `sed` on `tensorizer.py`.
  2. **Patch-2:** `TensorizerLoader.load_model` skips `process_weights_after_loading`, causing MoE kernel assertion failures. Fix: add `process_weights_after_loading` call (with `requires_grad_(False)` + `torch.no_grad()` guard) via Python patching of `tensorizer_loader.py`.
  These patches can be removed once vllm PR#33235 is merged and the TensorizerLoader is fixed upstream.
- **Loading speeds:** qwen2.5-1.5b: ~1.2s (2.5 GB/s). qwen3-235b: ~12s total (10 GB/s per GPU, 117.6 GB/rank). Compare to multi-minute HF downloads.
- For TP-sharded models (TP>1), `--model-loader-extra-config '{"tensorizer_uri": ".../model-rank-%03d.tensors"}'` is required.
- The PVC is `ReadWriteMany` (5Ti) — multiple pods across different nodes can mount it.
- **Sweep prompt contract:** The agent prompt in `ai_experiment.py` tells the LLM to PRESERVE the `command:` block, PVC volumes, and tensorizer flags. Only `vllm serve` flags (after `exec vllm serve ... \`) may be tuned. The model extraction regex looks for `--served-model-name` first.
- **Kimi vLLM exception:** Kimi-K2.5 on vLLM currently does *not* use tensorizer. It serves from HF safetensors cached under `/mnt/models/hf-cache` with `--trust-remote-code`. Tensorizer hit multiple incompatibilities with the multimodal + quantized Kimi stack on vLLM.
- **Kimi SGLang tensorizer:** `kimi-sglang-tensorizer/` is an experimental variant that adds tensorizer support to SGLang. The SGLang source at `autollm/sglang/` is patched with a `TensorizerModelLoader` (in `model_loader/loader.py`) that supports direct GPU deserialization via `load_into_module()`. Requires a one-time serialization step (`make tensorize` in the variant dir) and a custom Docker image (`lbiewald/sglang-tensorizer:latest`, built from `autollm/sglang/Dockerfile.tensorizer`). Serialized weights go to `/mnt/models/sglang/moonshotai/Kimi-K2.5/v1/model-rank-NNN.tensors`. The serialization hook uses `SGLANG_TENSORIZE_OUTPUT_DIR` / `SGLANG_TENSORIZE_AND_EXIT` env vars in `model_runner.py`.
- **Kimi concurrent variant:** `kimi-sglang-concurrent/` is based on the best sequential config from `sweep-kimi-sglang-large` (EAGLE3 + SPEC_V2 + fa3/flashinfer attention) but adapted for high-concurrency workloads: `--max-running-requests` removed (was 1), `--cuda-graph-max-bs 64` (was 16), `--num-continuous-decode-steps` removed (was 2, can starve concurrent requests), `--mem-fraction-static 0.80` (was 0.85, more KV cache headroom).
- **Kimi EAGLE-3 variant:** `kimi-sglang-eagle/` serves Kimi-K2.5 on SGLang with EAGLE-3 speculative decoding using `lightseekorg/kimi-k2.5-eagle3` as the draft model. Both the main model and draft model are cached on the PVC via `HF_HOME=/mnt/models/hf-cache`. The `pod.yaml` applies a startup patch to backport `set_eagle3_layers_to_capture` / `get_embed_and_head` / `set_embed_and_head` onto `KimiK25ForConditionalGeneration` (present on SGLang main but missing in v0.5.9). Remove the patch when upgrading past v0.5.9. Tested: ~2.6 tokens/step accept length, 65% acceptance rate.
- **Multithreaded safetensors loading:** SGLang variants use `--load-format safetensors --model-loader-extra-config '{"enable_multithread_load": true, "num_threads": 8}'` to load weights in parallel. This reduced Kimi-K2.5 loading from ~35 min to ~4 min on the NFS-backed `models` PVC. Available since SGLang v0.5.8+.
- **Kimi TensorRT-LLM variant:** `kimi-trt/` serves Kimi-K2.5 via `trtllm-serve` with `--backend pytorch` and 8× GPU tensor parallelism. Model weights are cached on the PVC via `HF_HOME=/mnt/models/hf-cache`. First startup may be slower due to engine optimization. Not yet tested end-to-end.

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

6. **Speculative decoding gotchas on this nightly:**
   `draft_model` speculative decoding is still broken with the tensorized main-model path on `v0.17.0rc1.dev204`, and `draft_load_config.load_format=auto` did not avoid the duplicate-layer startup failure. `ngram` works only with dot-notation CLI args (not the older JSON blob examples), but it regressed badly on the short synchronous qwen throughput benchmark (~521 tok/s vs 739 tok/s best), so treat it as workload-specific rather than a general win.

7. **Kimi-K2.5 improve runs may need a longer deploy hard timeout than the default 600s.**
   With multithreaded safetensors loading (`--load-format safetensors --model-loader-extra-config '{"enable_multithread_load": true, "num_threads": 8}'`), Kimi-K2.5 weight loading takes ~4 min instead of the previous ~35 min. Post-load CUDA warmup and graph capture add another few minutes. The default 600s timeout should be sufficient for SGLang variants, but vLLM variants without multithreaded loading may still need longer. The `benchmark_harness.py` health timeout is set to 45 min for 8-GPU models as a safety margin.

8. **Kimi sample queries can be reasoning-only.**
   Kimi-K2.5 may return `content: null` with non-empty `reasoning` or `reasoning_content` on short chat completions. Treat those as valid sample-query success in harness code; otherwise improve runs can redeploy forever even though the server is healthy.

9. **Backend-variant sweeps should keep their backend fixed unless you intentionally want backend swaps.**
   Family sweeps now default to all canonical variants for that family, but if a sweep is pinned to just one backend variant (for example via `BASELINE_VARIANT=kimi-sglang` plus a single-variant `MODEL_VARIANTS` override), `ai_experiment.py` should keep the prompt templates on that backend only.

10. **Repeated harness-only failures should stop retries early.**
   `ai_experiment.py` now short-circuits some known non-config retry loops (for example reasoning-only sample-query responses or pod-wait watchdog cases without a fatal server crash) so the next run can try a new experiment instead of wasting agent turns on the same harness issue.

11. **Unschedulable GPU pods are cluster-capacity failures, not repairable experiment failures.**
   If a run fails with `Pod unschedulable` / `Insufficient nvidia.com/gpu`, treat that as an immediate cluster-capacity stop condition. Do not let the retry loop spend turns "repairing" the YAML; wait for capacity or free GPUs first.

12. **EAGLE-3 for Kimi-K2.5 requires a startup patch on SGLang v0.5.9.**
   The `KimiK25ForConditionalGeneration` class in v0.5.9 lacks `set_eagle3_layers_to_capture()`, but the inner `DeepseekV3ForCausalLM` has it. The `kimi-sglang-eagle/pod.yaml` patches the outer class at startup to delegate to the inner model. This matches what SGLang main already has. Remove the patch when upgrading past v0.5.9.

13. **The `diverse` benchmark preset requires the dataset on the PVC.**
   The `diverse` preset uses `benchmarks/diverse/dataset.jsonl` which gets rewritten to `/mnt/models/benchmarks/diverse/dataset.jsonl` for K8s benchmark Jobs. Run `make sync-benchmarks` to copy the dataset to the PVC (requires a running pod with RW PVC access). If it fails because the only running pods mount the PVC read-only, create a temporary RW pod: `kubectl run pvc-writer --image=busybox --rm -it --restart=Never --overrides='...'`.

14. **Every runllm variant must mount the `models` PVC for model caching.**
   Without a PVC, HuggingFace models are re-downloaded from scratch on every pod restart — hundreds of GB for large models like Kimi-K2.5. For vLLM variants, use `--download-dir /mnt/models/hf-cache`. For SGLang variants, set the `HF_HOME` env var to `/mnt/models/hf-cache`. Always add the `models` PVC volume and volumeMount. This applies to both main models and draft/speculative models. When creating a new `runllm/` variant, copy the volume config from an existing variant rather than starting without it.

15. **Do not patch `node_modules/electron/dist/Electron.app` during Grist dev builds on macOS.**
   Rewriting `Info.plist` in-place can leave the dev app bundle in a bad state and cause `npm run dev` to die with an Electron `SIGKILL`. Keep the stock Electron app bundle untouched and customize app naming from Grist's own Electron code instead.

---

## Validation Shortlist

When changing this area, the cheap checks that have been useful are:

```bash
python3 -m py_compile scripts/ai_experiment.py scripts/agent_tools.py scripts/benchmark_config.py scripts/benchmark_harness.py scripts/run_guideline_experiment.py scripts/start_sweep.py scripts/sweep_utils.py scripts/list_sweep_pods.py
python3 -m py_compile scripts/vllm_profiling.py
python3 scripts/test_sweep_setup.py
env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --refresh-leaderboard --sweep qwen-throughput
```

For `runllm` changes:

```bash
bash -n runllm/qwen2.5-1.5b/test_smoke.sh
python3 -m py_compile runllm/qwen2.5-1.5b/query.py
```

---

## If You Add Durable Knowledge

If you discover something about the real architecture, contracts, failure modes, or operational pitfalls that future agents are likely to trip over again, add it here briefly. Keep this file focused on stable, high-value context rather than transient run results.
