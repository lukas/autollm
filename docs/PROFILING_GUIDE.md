# Profiling Guide for LLM Serving Optimization

How to diagnose performance bottlenecks before tuning.

---

## Quick Start

```bash
# Latency sweep against a running pod (~2 min):
make profile POD=<pod-name> MODEL_NAME=<hf-model-name>

# With nsys GPU kernel profiling (pod must use nsys launch):
make profile POD=<pod-name> MODEL_NAME=<hf-model-name> NSYS=1 NSYS_SESSION=<session>

# Custom output lengths:
make profile POD=<pod-name> MODEL_NAME=<hf-model-name> LENGTHS=16,64,256,1024,4096
```

Outputs land in `results/profile-<pod>/`:

| File | What it tells you |
|------|-------------------|
| `latency_table.txt` | Latency, throughput, ms/token at each output length |
| `latency_vs_seqlen.png` | Visual latency + throughput curves |
| `latency_results.json` | Raw data for further analysis |
| `kernel_summary.txt` | Top GPU kernels at each length (nsys only) |
| `nsys-reports/*.nsys-rep` | Full nsys traces for deep-dive (nsys only) |

---

## When to Profile

Run profiling **before** starting a sweep or when a sweep plateaus. It answers:
- Where is GPU time actually spent? (compute vs communication vs sampling)
- Does the bottleneck shift between short and long sequences?
- Is speculative decoding overhead worth the acceptance rate?
- Is the model memory-bound, compute-bound, or communication-bound?

---

## How to Read the Latency Table

```
Prompt     max_tok  Latency(s)   Comp Tok    Tok/s    ms/tok
short           16       0.432         16     37.0     27.00
short          256       3.210        256     79.8     12.54
short         2048      10.120       1842    182.0      5.49
```

Key patterns:
- **ms/tok decreasing with length** → model is amortizing startup/TTFT overhead. Normal.
- **ms/tok flat across lengths** → model is in steady-state generation mode. Good.
- **ms/tok increasing with length** → KV cache pressure or memory bandwidth saturation. Bad.
- **Tok/s much lower at short lengths** → communication overhead dominates (common with high TP).
- **Tok/s plateau at long lengths** → compute-saturated. Check if FP8/quantization helps.

---

## How to Read the Kernel Summary

The kernel summary groups GPU activity by operation type. Map kernel names to categories:

| Kernel pattern | Category | What it means |
|---------------|----------|---------------|
| `allreduce`, `cross_device_reduce`, `ncclDevKernel` | **Communication** | Inter-GPU data transfer (tensor parallelism) |
| `nvjet`, `Marlin`, `fused_a_gemm`, `cutlass` | **MoE/GEMM compute** | Matrix multiply (the actual "work") |
| `SoftMaxForward`, `FlashAttn`, `flash_fwd` | **Attention** | Attention computation |
| `TreeSpeculativeSampling`, `eagle` | **Spec decode** | Speculative decoding overhead |
| `TopPRenormProb`, `RadixTopK` | **Sampling** | Token sampling/selection |
| `elementwise`, `layernorm`, `rms_norm` | **Elementwise** | Normalization, activations |

### Decision Tree

```
If communication > 30% of GPU time:
  → TP degree too high for batch size / sequence length
  → Try: lower TP, increase batch size, or use pipeline parallelism

If attention > 25%:
  → Try: FlashAttention 3, different attention backend, FP8 KV cache

If MoE GEMM > 40%:
  → Compute-bound (good — means GPU is doing useful work)
  → Try: FP8/INT4 quantization, expert parallelism tuning

If spec decode > 10%:
  → Overhead too high for acceptance rate
  → Check acceptance rate: if < 50%, speculative decoding hurts more than helps

If sampling > 5%:
  → Unusual; check if top-k/top-p settings are pathological
```

---

## Setting Up nsys Profiling

nsys requires wrapping the server process at launch time. Modify the pod's `args` to prepend `nsys launch`:

```yaml
args:
  - |
    nsys launch \
      --trace=cuda,nvtx \
      --cuda-memory-usage=true \
      --session-new=my_profile \
      -- \
    python -m sglang.launch_server --model ... [rest of args]
```

Important:
- Set `restartPolicy: Never` (manual control during profiling)
- Remove `--sample=none` (not supported in recent nsys versions)
- The `--session-new=my_profile` name must match `--nsys-session` in the profile command

### Manual nsys from inside the pod

```bash
# Start profiling a specific request:
kubectl exec <pod> -- nsys start --session=my_profile -o /tmp/trace_name --force-overwrite=true

# Send your request (curl, benchmark, etc.)

# Stop and save:
kubectl exec <pod> -- nsys stop --session=my_profile

# Get kernel summary:
kubectl exec <pod> -- nsys stats /tmp/trace_name.nsys-rep --report cuda_gpu_kern_sum --format csv

# Copy report locally:
kubectl cp <pod>:/tmp/trace_name.nsys-rep ./trace_name.nsys-rep
```

---

## For Autoresearch Agents

### Using profiling data in sweep planning

1. **Before a sweep:** Run `make profile` on the baseline config. Include `latency_table.txt` and `kernel_summary.txt` in the agent's context.

2. **Interpreting for optimization:**
   - If communication-bound at short sequences but compute-bound at long ones → the benchmark workload mix matters. Optimize for the dominant sequence length.
   - If speculative decoding shows high overhead + low acceptance → disable it or try a better draft model.
   - If attention is dominant → try FP8 KV cache, chunked prefill tuning, or FlashAttention 3.

3. **Via agent tools:** The agent can run profiling via `run_shell`:
   ```python
   run_shell("python scripts/profile_model.py --pod <pod> --model <model> --output-dir results/sweep-NAME/profile")
   ```
   Then read the compact outputs:
   ```python
   read_file("results/sweep-NAME/profile/latency_table.txt")
   read_file("results/sweep-NAME/profile/kernel_summary.txt")
   ```

### Reference: Kimi-K2.5 on 8xH200 (SGLang + EAGLE-3)

Profiled at different output lengths (representative baseline):

| Length | Bottleneck | Communication% | Compute% | Notes |
|--------|-----------|----------------|----------|-------|
| 64 tok | Communication | ~62% allreduce | ~15% MoE | TP=8 overhead dominates short requests |
| 256 tok | Mixed | ~35% allreduce | ~30% MoE | Transitioning to compute-bound |
| 1024 tok | Compute | ~20% allreduce | ~45% MoE+attn | Healthy compute utilization |
| 2048 tok | Compute | ~13% allreduce | ~55% MoE+attn | Throughput saturated at ~220 tok/s |

This shows that for Kimi on 8xH200, short requests are heavily communication-bound (TP=8 is expensive for low token counts), while longer sequences make good use of the GPUs. Optimization strategies differ by target workload.
