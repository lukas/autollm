# Agent Handoff: autollm Sweep Workflow

**Purpose:** durable context for future agents working on `autollm`. Read this before changing sweep/improve behavior, benchmark flow, or `runllm` integration.

---

## Current Primary Workflow

The main path is the sweep workflow, not the older dashboard optimizer:

```bash
make sweep SWEEP=qwen-latency MODEL_DIR=qwen2.5-1.5b GOAL="minimize latency"
make sweep SWEEP=qwen3-235b-throughput MODEL_DIR=qwen3-235b GOAL="maximize throughput"
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
| `scripts/vllm_profiling.py` | Shared helpers for periodic vLLM `/metrics` sampling, best-effort GPU sampling, and hardware profile summaries |
| `scripts/run_guideline_experiment.py` | Guideline subprocess wrapper for experiment mode; writes `query_progress.json` |
| `scripts/start_sweep.py` | Baseline sweep creation |
| `scripts/sweep_utils.py` | Best-run scoring and objective helpers |
| `runllm/<model>/` | Per-model vLLM deploy/query/test directories (e.g. `qwen2.5-1.5b/`, `qwen3-235b/`, `kimi/`). Each has `vllm-config.yaml`, `Makefile`, `query.py`, `test_smoke.sh`. |
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
- `write_file` is sandboxed: only writes `vllm-config.yaml` or `Makefile` to the isolated per-run experiment directory (`results/sweep-NAME/TIMESTAMP/runllm/`). It never touches the shared project `runllm/`.
- Web search uses Exa API (`EXA_API_KEY`). Falls back to DuckDuckGo HTML scraping if the key is unset. The key is read from the environment or `.env` file.

### Run Retros

- Every run (success or failure) writes a `RETRO.md` via `_write_run_retro()` in `ai_experiment.py`.
- The retro agent gets up to 10 tool calls to inspect logs and gather evidence.
- Retros are designed for consumption by future AI agents. They capture: exact knob changes, key metrics or errors, causal explanations, crashes from any phase, research findings, and non-obvious pitfalls.
- Retros should be terse (3-10 lines) but complete.
- If a single run directory contains multiple internal attempts, new retros are appended to `RETRO.md` with a markdown separator instead of overwriting the previous attempt.
- New improve prompts include both the newest per-run `RETRO.md` in the sweep and the synthesized `FULL_RETRO.txt`, so the next agent sees the freshest local context plus the higher-level summary.

### Benchmark / Retry Flow

- `ai_experiment.py` uses up to 10 internal attempts per improve run.
- Improve runs are now intended to test one experiment hypothesis per run directory. Internal retries are for debugging that same experiment when the benchmark exposed a crash/startup/harness bug, not for pivoting to a new tuning idea.
- A retry can return `NO_CONFIG_CHANGE`, which now means “stop this run and let the next run/agent choose the next experiment”, not “rerun benchmark with the same YAML”.
- Benchmark output is more verbose now:
  - live `guidellm` output is streamed into the terminal
  - stalled runs print periodic waiting messages with the last harness line
- The old 180s generic abort no longer kills benchmarks that are still making request progress.
- Both `make improve` and `make benchmark` now run a lightweight profiler during the benchmark:
  - samples vLLM `/metrics` every few seconds into `vllm_metrics_timeseries.jsonl`
  - writes a compact `vllm_metrics_profile.json` summary with queue/cache/throughput peaks and diagnosis hints
  - writes `hardware_context.json` with node placement and resource limits
  - writes `gpu_metrics_timeseries.jsonl` if `nvidia-smi` is available inside the pod
- If you are debugging a bad run, check `vllm_metrics_profile.json` before reading raw logs. It often tells you whether the failure was KV cache pressure, queue buildup, or low GPU utilization.
- A single improve run directory can contain multiple internal attempts. When reading a bad `RETRO.md`, verify the final outcome against `results.txt`, `benchmarks.json`, and the terminal output if the retro seems inconsistent.

### Pod Management

- Improve runs use unique pod names like `<base-pod-name>-<timestamp_suffix>` (base name is read from the YAML `metadata.name`).
- Pods are labeled for sweep discovery:
  - `autollm-managed: "true"`
  - `autollm-sweep: "<sweep-name>"`
- Pod cleanup happens on success, failure, and normal signal exit.
- `make sweep-pods` depends on those labels.

### runllm Surface

- `autollm/runllm/` contains per-model subdirectories (e.g. `qwen2.5-1.5b/`, `qwen3-235b/`, `kimi/`).
- Each model dir is self-contained with `vllm-config.yaml`, `Makefile`, `query.py`, `test_smoke.sh`.
- The top-level sibling `../runllm` was intentionally removed.
- `query.py` and `test_smoke.sh` use `/v1/chat/completions`.
- Each Makefile respects exported `KUBECONFIG` and otherwise falls back to `../../kubeconfig`.
- Sweeps store `model_dir` in `sweep_metadata.json` so `make improve` uses the right model config.

### Tensorizer / PVC Model Loading

- All models use `--load-format tensorizer` with pre-serialized weights on a shared PVC (`tensorized-models`, 1Ti, `shared-vast`). The PVC mounts at `/mnt/tensorized/`. Serialized weights at `/mnt/tensorized/vllm/<org>/<model>/v1/`.
- PVC definition: `runllm/tensorized-models-pvc.yaml`.
- To serialize: `make tensorize MODEL_DIR=qwen2.5-1.5b` (K8s Job; idempotent — skips if marker file already exists on PVC).
- The nightly vllm image doesn't bundle tensorizer, so all configs use `command: ["/bin/bash", "-c"]` to `pip install tensorizer` before `vllm serve`.
- All configs use `--served-model-name <HF-name>` (e.g. `Qwen/Qwen2.5-1.5B-Instruct`) so the API model name matches what Makefiles and query scripts expect, even though the actual `--model` path points to the PVC.
- **Startup patches (applied at container init):** Two vllm bugs require runtime patching in the init script:
  1. **Patch-1 (vllm#25751):** `MetaTensorMode` only intercepts `aten::empty`, causing 2x GPU memory during deserialization. Fix: expand to 18 factory ops via `sed` on `tensorizer.py`.
  2. **Patch-2:** `TensorizerLoader.load_model` skips `process_weights_after_loading`, causing MoE kernel assertion failures. Fix: add `process_weights_after_loading` call (with `requires_grad_(False)` + `torch.no_grad()` guard) via Python patching of `tensorizer_loader.py`.
  These patches can be removed once vllm PR#33235 is merged and the TensorizerLoader is fixed upstream.
- **Loading speeds:** qwen2.5-1.5b: ~1.2s (2.5 GB/s). qwen3-235b: ~12s total (10 GB/s per GPU, 117.6 GB/rank). Compare to multi-minute HF downloads.
- For TP-sharded models (TP>1), `--model-loader-extra-config '{"tensorizer_uri": ".../model-rank-%03d.tensors"}'` is required.
- The PVC is `ReadWriteOnce` — multiple pods can mount it on the same node but not across nodes.
- **Sweep prompt contract:** The agent prompt in `ai_experiment.py` tells the LLM to PRESERVE the `command:` block, PVC volumes, and tensorizer flags. Only `vllm serve` flags (after `exec vllm serve ... \`) may be tuned. The model extraction regex looks for `--served-model-name` first.

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
