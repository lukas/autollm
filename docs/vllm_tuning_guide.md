# vLLM Optimization and Tuning Guide

Source: https://docs.vllm.ai/en/stable/configuration/optimization/

## Preemption

When KV cache space is insufficient, vLLM preempts requests (recomputes them later).
Warning sign: `Sequence group is preempted by PreemptionMode.RECOMPUTE`

**Fixes:**
- Increase `gpu_memory_utilization` (more KV cache space)
- Decrease `max_num_seqs` or `max_num_batched_tokens` (fewer concurrent requests)
- Increase `tensor_parallel_size` (more total GPU memory)

Monitor preemption count via Prometheus metrics (`vllm:num_preemptions_total`).
Set `disable_log_stats=False` to log cumulative preemption count.

## Chunked Prefill

In V1, chunked prefill is **enabled by default**. Scheduling prioritizes decode requests,
then fills remaining `max_num_batched_tokens` budget with prefills.

**Tuning `max_num_batched_tokens`:**
- Smaller values (e.g. 2048) → better ITL (fewer prefills blocking decodes)
- Larger values → better TTFT (more prefill tokens per batch)
- For optimal throughput on small models with large GPUs: set > 8192
- Setting equal to `max_model_len` ≈ V0 default scheduling (still decode-priority)

**Sub-knobs for chunked prefill:**
- `--max-num-partial-prefills` — max concurrent partial prefills (default: 1)
- `--max-long-partial-prefills` — max concurrent long partial prefills
- `--long-prefill-token-threshold` — threshold for "long" prefill classification

Lowering `max-long-partial-prefills` relative to `max-num-partial-prefills` lets shorter
prompts jump ahead, improving latency for mixed workloads.

## CPU Resources for GPU Deployments

Minimum physical cores: `2 + N` (1 API server + 1 engine core + N GPU workers).
With hyperthreading: need `2 × (2 + N)` vCPUs.

**CPU underprovisioning impacts:**
- Input processing throughput (tokenization, chat template rendering)
- Scheduling latency (engine core scheduler is CPU-bound)
- Output processing (detokenization, streaming responses)

Low GPU utilization often signals CPU contention, not a GPU config issue.

## Attention Backend Selection

vLLM auto-selects attention backend based on GPU architecture, model type, and config.
You can manually specify one. Backends include:
- FLASH_ATTN — standard FlashAttention
- FLASHINFER — alternative implementation, sometimes faster
- auto — let vLLM pick the best for your hardware

Set via `VLLM_ATTENTION_BACKEND` env var or `--attention-backend` flag.

## Key Prometheus Metrics (/metrics endpoint)

Server-side metrics available at `http://localhost:8000/metrics`:
- `vllm:num_preemptions_total` — cumulative preemption count
- `vllm:gpu_cache_usage_perc` — GPU KV cache utilization (0-1)
- `vllm:cpu_cache_usage_perc` — CPU KV cache utilization (0-1)
- `vllm:num_requests_waiting` — requests queued waiting for processing
- `vllm:num_requests_running` — requests currently being processed
- `vllm:avg_prompt_throughput_toks_per_s` — prompt processing throughput
- `vllm:avg_generation_throughput_toks_per_s` — generation throughput
- `vllm:e2e_request_latency_seconds_{sum,count}` — end-to-end latency
- `vllm:time_to_first_token_seconds_{sum,count}` — TTFT from server side

## Parallelism Strategies

- **Tensor Parallelism (TP):** Shard model weights across GPUs within a layer. Essential when model doesn't fit on one GPU.
- **Pipeline Parallelism (PP):** Distribute layers across GPUs. Use after maxing TP.
- **Data Parallelism (DP):** Replicate model, process different batches in parallel. Use for throughput scaling.

## CUDA Graphs

CUDA graph capture can significantly accelerate inference by replaying GPU kernel sequences.
- `--enforce-eager` disables CUDA graphs (can reduce TTFT but hurts throughput)
- `--compilation-config '{"mode": 3}'` enables max-autotune (slowest startup, best perf)
- Graph capture sizing matters: capturing many large graphs increases startup time with limited benefit for small batch sizes.

## Speculative Decoding

- Draft model: uses a smaller model to predict tokens, verified by main model
- N-gram speculation: lightweight, no extra model needed
- Suffix decoding: lightweight alternative
- Not universally faster; test carefully
