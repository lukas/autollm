#!/usr/bin/env python3
"""Profile a running LLM serving pod: latency by sequence length + nsys GPU kernel breakdown.

Outputs:
  - <output_dir>/latency_results.json       — raw latency data
  - <output_dir>/latency_table.txt          — human-readable table
  - <output_dir>/latency_vs_seqlen.png      — latency graph
  - <output_dir>/nsys-reports/*.nsys-rep     — nsys profiles (if --nsys)
  - <output_dir>/kernel_summary.txt         — top GPU kernels per length

Usage:
  # Latency sweep only (fast, ~2min):
  python scripts/profile_model.py --pod sglang-kimi-bench --model moonshotai/Kimi-K2.5

  # With nsys profiling (requires pod started via nsys launch):
  python scripts/profile_model.py --pod sglang-kimi-bench --model moonshotai/Kimi-K2.5 --nsys --nsys-session kimi_profile

  # Custom output lengths:
  python scripts/profile_model.py --pod vllm-qwen --model Qwen/Qwen2.5-1.5B-Instruct --lengths 16,64,256,1024

Prerequisites:
  - kubectl configured and able to reach the cluster
  - A running serving pod with port 8000 exposed internally
  - For nsys: pod must be started with `nsys launch --session-new=<name> --trace=cuda,nvtx ...`

For the autoresearch agent:
  This script can be called via run_shell to generate profiling data before planning
  optimization strategies. The latency_table.txt and kernel_summary.txt are compact
  enough to include in agent context.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def kubectl(*args, timeout=30):
    """Run kubectl and return stdout."""
    r = subprocess.run(
        ["kubectl", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {r.stderr[:500]}")
    return r.stdout.strip()


def get_pod_ip(pod_name):
    return kubectl("get", "pod", pod_name, "-o", "jsonpath={.status.podIP}")


def send_request(pod_ip, model, prompt, max_tokens):
    """Send a request via kubectl exec + curl and parse the response."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    })
    # Use kubectl exec to send request from inside the cluster
    cmd = [
        "kubectl", "exec", pod_name_global, "--",
        "curl", "-s", "--max-time", "300",
        f"http://localhost:8000/v1/chat/completions",
        "-H", "Content-Type: application/json",
        "-d", body,
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=320)
    t1 = time.time()
    if r.returncode != 0:
        return {"error": r.stderr[:200], "latency": t1 - t0}
    try:
        data = json.loads(r.stdout)
        usage = data.get("usage", {})
        return {
            "latency": round(t1 - t0, 3),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    except json.JSONDecodeError:
        return {"error": "JSON decode failed", "latency": t1 - t0, "raw": r.stdout[:200]}


PROMPTS = {
    "short": "What is 2+2?",
    "medium": (
        "Explain the history of the Roman Empire from its founding to its fall. "
        "Cover the key periods including the Kingdom, the Republic, and the Empire. "
        "Discuss the major political, military, and cultural developments."
    ),
    "long": (
        "Write a detailed, comprehensive analysis of the causes, major events, "
        "and consequences of World War II. Cover the political tensions in Europe "
        "and Asia during the 1930s, the key military campaigns, the role of "
        "technology and intelligence, the home front in major belligerent nations, "
        "the Holocaust, the use of atomic weapons, and the post-war settlement."
    ),
}


def run_latency_sweep(pod_name, model, lengths, reps=2):
    """Run requests at different max_tokens and measure latency."""
    print(f"Pod: {pod_name}  Model: {model}")
    print(f"Lengths: {lengths}  Reps: {reps}")
    print()

    # Warmup
    print("Warmup...", end=" ", flush=True)
    r = send_request(None, model, "Hi", 8)
    print(f"OK ({r.get('latency', '?')}s)")
    print()

    results = []
    for prompt_label, prompt in PROMPTS.items():
        print(f"=== Prompt: {prompt_label} ===")
        for max_tok in lengths:
            latencies = []
            comp_tokens_list = []
            for rep in range(reps):
                r = send_request(None, model, prompt, max_tok)
                if "error" not in r:
                    latencies.append(r["latency"])
                    comp_tokens_list.append(r["completion_tokens"])
                    results.append({
                        "prompt_label": prompt_label,
                        "max_tokens": max_tok,
                        **r,
                    })
                else:
                    print(f"  max_tokens={max_tok} rep={rep} ERROR: {r.get('error','?')}")

            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                avg_tok = sum(comp_tokens_list) / len(comp_tokens_list)
                tps = avg_tok / avg_lat if avg_lat > 0 else 0
                print(
                    f"  max_tokens={max_tok:>5}  "
                    f"latency={avg_lat:>7.2f}s  "
                    f"comp_tok={avg_tok:>6.0f}  "
                    f"tok/s={tps:>6.1f}"
                )
        print()
    return results


def make_latency_table(results):
    """Generate a compact latency table for agent consumption."""
    from collections import defaultdict
    agg = defaultdict(lambda: {"latencies": [], "tokens": []})
    for r in results:
        if "error" in r:
            continue
        key = (r["prompt_label"], r["max_tokens"])
        agg[key]["latencies"].append(r["latency"])
        agg[key]["tokens"].append(r["completion_tokens"])

    lines = []
    lines.append("LATENCY vs SEQUENCE LENGTH")
    lines.append("=" * 85)
    lines.append(f"{'Prompt':<10} {'max_tok':>8} {'Latency(s)':>11} {'Comp Tok':>10} {'Tok/s':>8} {'ms/tok':>8}")
    lines.append("-" * 85)

    for prompt_label in ["short", "medium", "long"]:
        for (pl, mt), v in sorted(agg.items(), key=lambda x: (x[0][0], x[0][1])):
            if pl != prompt_label:
                continue
            avg_lat = sum(v["latencies"]) / len(v["latencies"])
            avg_tok = sum(v["tokens"]) / len(v["tokens"])
            tps = avg_tok / avg_lat if avg_lat > 0 else 0
            ms_per_tok = (avg_lat / avg_tok * 1000) if avg_tok > 0 else 0
            lines.append(
                f"{pl:<10} {mt:>8} {avg_lat:>11.3f} {avg_tok:>10.0f} {tps:>8.1f} {ms_per_tok:>8.2f}"
            )
        lines.append("")

    return "\n".join(lines)


def make_latency_plot(results, output_path):
    """Generate latency vs sequence length plot."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib not available, skipping plot")
        return

    from collections import defaultdict
    agg = defaultdict(lambda: {"latencies": [], "tokens": []})
    for r in results:
        if "error" in r:
            continue
        key = (r["prompt_label"], r["max_tokens"])
        agg[key]["latencies"].append(r["latency"])
        agg[key]["tokens"].append(r["completion_tokens"])

    colors = {"short": "#2196F3", "medium": "#FF9800", "long": "#4CAF50"}
    markers = {"short": "o", "medium": "s", "long": "^"}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    for prompt_label in ["short", "medium", "long"]:
        xs_tok, ys_lat, ys_tps = [], [], []
        for (pl, mt), v in sorted(agg.items(), key=lambda x: x[0][1]):
            if pl != prompt_label:
                continue
            avg_tok = np.mean(v["tokens"])
            avg_lat = np.mean(v["latencies"])
            xs_tok.append(avg_tok)
            ys_lat.append(avg_lat * 1000)
            ys_tps.append(avg_tok / avg_lat if avg_lat > 0 else 0)

        ax1.plot(xs_tok, ys_lat, marker=markers[prompt_label], color=colors[prompt_label],
                 label=f"{prompt_label} prompt", linewidth=2, markersize=8)
        if any(t > 10 for t in xs_tok):
            ax2.plot(
                [x for x in xs_tok if x > 10],
                [t for x, t in zip(xs_tok, ys_tps) if x > 10],
                marker=markers[prompt_label], color=colors[prompt_label],
                label=f"{prompt_label} prompt", linewidth=2, markersize=8,
            )

    ax1.set_xlabel("Output Tokens", fontsize=12)
    ax1.set_ylabel("Total Latency (ms)", fontsize=12)
    ax1.set_title("Latency vs Output Length", fontsize=13, fontweight="bold")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.set_xlabel("Output Tokens", fontsize=12)
    ax2.set_ylabel("Throughput (tok/s)", fontsize=12)
    ax2.set_title("Throughput vs Output Length", fontsize=13, fontweight="bold")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def run_nsys_profiles(pod_name, model, session_name, lengths, output_dir):
    """Run nsys start/stop around requests at each length."""
    nsys_dir = output_dir / "nsys-reports"
    nsys_dir.mkdir(exist_ok=True)

    configs = []
    for max_tok in lengths:
        if max_tok <= 64:
            label = f"short_{max_tok}"
            prompt = PROMPTS["short"]
        elif max_tok <= 512:
            label = f"medium_{max_tok}"
            prompt = PROMPTS["medium"]
        else:
            label = f"long_{max_tok}"
            prompt = PROMPTS["long"]
        configs.append((label, max_tok, prompt))

    all_kernel_data = {}

    for label, max_tok, prompt in configs:
        print(f"\n==> nsys profile: {label} (max_tokens={max_tok})")
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tok,
            "temperature": 0.7,
            "stream": False,
        })

        script = f"""
nsys start --session={session_name} --sample=none -o /tmp/nsys_{label} --force-overwrite=true 2>&1
sleep 1
curl -s --max-time 120 http://localhost:8000/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{body}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
u=r.get('usage',{{}})
print('Tokens: prompt=%d completion=%d' % (u.get('prompt_tokens',0), u.get('completion_tokens',0)))
"
nsys stop --session={session_name} 2>&1 | tail -3
"""
        try:
            r = subprocess.run(
                ["kubectl", "exec", pod_name, "--", "bash", "-c", script],
                capture_output=True, text=True, timeout=180,
            )
            print(f"  {r.stdout.strip()}")
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT")
            continue

        # Get kernel summary
        try:
            kr = subprocess.run(
                ["kubectl", "exec", pod_name, "--", "nsys", "stats",
                 f"/tmp/nsys_{label}.nsys-rep", "--report", "cuda_gpu_kern_sum",
                 "--format", "csv", "--force-export=true"],
                capture_output=True, text=True, timeout=30,
            )
            if kr.returncode == 0 and "Time (%)" in kr.stdout:
                all_kernel_data[label] = kr.stdout
        except Exception:
            pass

        # Copy report locally
        try:
            subprocess.run(
                ["kubectl", "cp", f"{pod_name}:/tmp/nsys_{label}.nsys-rep",
                 str(nsys_dir / f"nsys_{label}.nsys-rep")],
                capture_output=True, timeout=60,
            )
            print(f"  Copied to {nsys_dir}/nsys_{label}.nsys-rep")
        except Exception:
            print(f"  (failed to copy report)")

    return all_kernel_data


def make_kernel_summary(kernel_data):
    """Parse CSV kernel data and produce a compact summary table."""
    import csv
    import io

    lines = []
    lines.append("CUDA GPU KERNEL BREAKDOWN BY SEQUENCE LENGTH")
    lines.append("=" * 100)
    lines.append("(Top 10 kernels by GPU time for each output length)")
    lines.append("")

    for label, csv_text in sorted(kernel_data.items()):
        lines.append(f"--- {label} ---")
        reader = csv.reader(io.StringIO(csv_text))
        header = None
        rows = []
        for row in reader:
            if not row:
                continue
            if "Time (%)" in row[0] or "Time" in row[0]:
                header = row
                continue
            if header and len(row) >= len(header):
                rows.append(row)

        if not rows:
            lines.append("  (no kernel data)")
            lines.append("")
            continue

        lines.append(f"  {'Time%':>6}  {'Total(ms)':>10}  {'Instances':>10}  {'Avg(us)':>10}  Kernel")
        for row in rows[:10]:
            try:
                pct = float(row[0])
                total_ns = int(row[1].replace(",", ""))
                instances = int(row[2].replace(",", ""))
                avg_ns = float(row[3].replace(",", ""))
                name = row[-1][:80]
                lines.append(
                    f"  {pct:>5.1f}%  {total_ns/1e6:>10.2f}  {instances:>10}  {avg_ns/1e3:>10.1f}  {name}"
                )
            except (ValueError, IndexError):
                continue
        lines.append("")

    lines.append("")
    lines.append("KEY CATEGORIES (look for these patterns):")
    lines.append("  allreduce / cross_device_reduce  → inter-GPU communication (TP overhead)")
    lines.append("  nvjet / Marlin / fused_a_gemm    → MoE expert GEMMs (actual compute)")
    lines.append("  SoftMaxForward / FlashAttn       → attention computation")
    lines.append("  TreeSpeculativeSampling          → EAGLE/speculative decoding overhead")
    lines.append("  ncclDevKernel                    → NCCL collective communication")
    lines.append("  TopPRenormProb / RadixTopK       → sampling overhead")
    lines.append("")
    lines.append("OPTIMIZATION HINTS:")
    lines.append("  - If allreduce > 30%: TP degree too high for this workload, or batch too small")
    lines.append("  - If softmax/attention > 20%: try FlashAttention3 or different attention backend")
    lines.append("  - If MoE GEMM dominant: check expert parallelism, quantization (FP8/INT4)")
    lines.append("  - If sampling > 5%: speculative decode overhead may not be paying off")
    lines.append("  - Compare short vs long: if short is allreduce-heavy, batching will help")

    return "\n".join(lines)


def main():
    global pod_name_global

    parser = argparse.ArgumentParser(description="Profile LLM serving: latency + GPU kernels")
    parser.add_argument("--pod", required=True, help="Kubernetes pod name")
    parser.add_argument("--model", required=True, help="Model name for API calls")
    parser.add_argument("--lengths", default="16,64,128,256,512,1024,2048",
                        help="Comma-separated max_tokens values")
    parser.add_argument("--reps", type=int, default=2, help="Repetitions per config")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: results/profile-<pod>)")
    parser.add_argument("--nsys", action="store_true", help="Run nsys profiling (pod must use nsys launch)")
    parser.add_argument("--nsys-session", default="profile_session",
                        help="nsys session name (set in nsys launch --session-new=)")
    parser.add_argument("--nsys-lengths", default=None,
                        help="Comma-separated lengths for nsys (default: 64,256,1024,2048)")
    args = parser.parse_args()

    pod_name_global = args.pod
    lengths = [int(x) for x in args.lengths.split(",")]
    output_dir = Path(args.output_dir or f"results/profile-{args.pod}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Latency sweep
    print("=" * 60)
    print("PHASE 1: Latency Sweep")
    print("=" * 60)
    results = run_latency_sweep(args.pod, args.model, lengths, reps=args.reps)

    (output_dir / "latency_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nRaw results: {output_dir}/latency_results.json")

    table = make_latency_table(results)
    (output_dir / "latency_table.txt").write_text(table)
    print(f"\n{table}")

    make_latency_plot(results, output_dir / "latency_vs_seqlen.png")

    # 2. nsys profiling (optional)
    if args.nsys:
        print("\n" + "=" * 60)
        print("PHASE 2: nsys GPU Kernel Profiling")
        print("=" * 60)
        nsys_lengths = [int(x) for x in (args.nsys_lengths or "64,256,1024,2048").split(",")]
        kernel_data = run_nsys_profiles(
            args.pod, args.model, args.nsys_session, nsys_lengths, output_dir,
        )
        if kernel_data:
            summary = make_kernel_summary(kernel_data)
            (output_dir / "kernel_summary.txt").write_text(summary)
            print(f"\n{summary}")
        else:
            print("\nNo kernel data captured. Ensure pod was started with nsys launch.")

    print(f"\n{'=' * 60}")
    print(f"All outputs in: {output_dir}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
