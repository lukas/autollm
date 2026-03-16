# Sweep Best Practices

Practical guidance for future agents running `autollm` sweeps. This is based on the current `qwen`, `qwen3-235b`, `kimi-vllm`, and `kimi-sglang` sweep results.

## 1. Make comparisons apples-to-apples

- Do not compare runs across different benchmark presets. `quick` synchronous `64/64` results and `large` concurrent `256/128` results answer different questions.
- Before claiming an improvement, verify the sweep's `OVERVIEW.md` matches the comparison target on:
  - benchmark preset
  - profile (`synchronous` vs `concurrent`)
  - prompt/output token sizes
  - request/time limits
- Treat `TTFT: 0ms` as suspect on Kimi-family runs. The throughput/latency numbers may still be usable, but TTFT instrumentation is not always trustworthy there.

## 2. Semantic correctness comes before throughput

- A pod reaching `Ready` and returning HTTP 200 is not enough. The sample query must return a semantically valid response for the harness and benchmark client.
- For Kimi/Kimi-SGLang, watch for `message.content=null` with text only in `reasoning` or `reasoning_content`. That is a common failure mode and can make a benchmark look faster or healthier than it really is.
- If the response schema is wrong, stop tuning performance knobs and fix the serving/harness compatibility issue first.

## 3. Preserve the winning scaffold; change one real knob

- The biggest wins came from a few high-impact scaffold choices, not from broad random exploration.
- For `qwen` throughput sweeps, strong defaults like async scheduling, chunked prefill, prefix caching, and the right `max_num_batched_tokens` / `block_size` mattered much more than minor env var tweaks.
- For `qwen3-235b`, the good regime was narrow and workload-specific. Small local searches near the current winner worked better than broad knob sweeps.
- For Kimi, backend/framework compatibility dominated many runs. Avoid spending runs on tiny perf tweaks until startup and response shape are stable.
- Use one experiment per run. Do not bundle scheduler, batching, compilation, and memory changes together.

## 4. Treat some knobs as local searches, not global trends

- `max_num_seqs`, `max_num_batched_tokens`, `long_prefill_token_threshold`, and similar scheduler/prefill knobs often have sharp local optima.
- If a sweep shows a narrow sweet spot, only probe the immediate neighborhood around the current winner.
- Do not assume monotonic behavior from "more memory", "more batching", or "higher concurrency caps".
- In the `qwen` sweeps, several knobs improved only when tuned just above the live concurrency boundary; larger jumps often regressed badly.

## 5. Be skeptical of small deltas

- Cluster variance is real. If a change is only a few percent better, assume noise until it repeats.
- Prefer repeated wins or wins that also improve the surrounding profile evidence:
  - better queue behavior
  - lower TTFT without hurting throughput
  - better GPU utilization with stable correctness
- "Baseline reproductions" and "variance checks" were useful in multiple sweeps; use them when the leaderboard is flat.

## 6. Read profile evidence before inventing new knobs

- Check `vllm_metrics_profile.json`, `hardware_context.json`, and GPU metrics before making the next change.
- If waiting queue and preemptions are near zero, the system may not be scheduler-limited.
- If GPU memory is far from saturated, memory reservation tweaks are unlikely to help.
- If logs repeatedly warn about a slow tokenizer, tokenizer or prompt formatting overhead may matter more than GPU knobs.
- For some Kimi-SGLang runs, GPU memory stayed near only ~50% while throughput was already flat, so memory tuning was the wrong axis.

## 7. Avoid known bad classes of experiments

- Do not force unsupported or poorly supported backends/flags just because they sound faster:
  - invalid attention backends
  - speculative decoding paths that conflict with async scheduling
  - FP8 KV cache modes that mismatch the active backend/kernel path
  - invalid compilation config schemas
- For Kimi-SGLang specifically, parser/tool-call flag changes were often really response-shape experiments, not throughput experiments.
- For explicit backend-variant sweeps like `kimi-sglang`, keep the backend fixed unless the point of the run is an intentional backend swap.

## 8. Startup and harness reliability are part of the experiment

- A surprising number of failed runs were harness or lifecycle issues rather than real model regressions.
- Preserve diagnostics on failures: pod status, events, describe output, and current/previous logs.
- Be careful with retry pod naming and cleanup. Reusing a stable canonical pod base name matters.
- Remote sweeps should clean up pid files and ignore zombie controller-side shells; stale status can waste time and confuse comparisons.

## 9. Model-specific guidance

- `qwen2.5-1.5b`: throughput responds well to careful scheduler/prefill tuning. This is the best family for tight local search.
- `qwen3-235b`: broad experimentation found real wins, but many backend/compiler/MoE changes were harmful or unstable. Be conservative once you are near the top of the leaderboard.
- `kimi-vllm`: current `quick` harness is too low-load to expose many server-side improvements. Throughput conclusions there are weak unless the workload is made more demanding.
- `kimi-sglang`: current large sweep evidence suggests parser-free, schema-safe configs are the valid comparison set. Treat the old parser-enabled large baseline with caution.

## 10. Recommended future-agent workflow

1. Verify the benchmark is the right one and comparisons are apples-to-apples.
2. Confirm the current best config is semantically correct with the exact sample query path used by the harness.
3. Read the latest `FULL_RETRO.txt`, then inspect the winner's `vllm_metrics_profile.json`.
4. Choose one high-leverage knob adjacent to the current winner; avoid broad pivots unless the evidence says the current axis is exhausted.
5. If the measured gain is small, rerun or validate against variance before declaring victory.
