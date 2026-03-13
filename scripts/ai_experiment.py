#!/usr/bin/env python3
"""
AI experiment: show agent (Opus/Codex) runllm code + benchmark data, get suggested changes,
write modified runllm to results/runs or results/sweep-NAME/ only (never project root), deploy, benchmark.

Usage:
  AI_PROVIDER=anthropic AI_MODEL=claude-opus-4-6 make experiment
  AI_PROVIDER=openai AI_MODEL=gpt-4o make experiment
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from agent_tools import AgentResult, ToolContext, run_agent
from benchmark_config import BENCHMARK_MAX_REQUESTS, BENCHMARK_PRESETS
from sweep_utils import completed_request_count, is_valid_run, metric_mean, sweep_objective, sweep_ranking_label
from vllm_profiling import VLLMProfiler, write_vllm_snapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_KUBECONFIG = PROJECT_ROOT / "kubeconfig"
if not os.environ.get("KUBECONFIG") and _DEFAULT_KUBECONFIG.exists():
    os.environ["KUBECONFIG"] = str(_DEFAULT_KUBECONFIG)

# Track active pods for cleanup on exit/Ctrl+C
_active_pods: list[str] = []
_cleanup_env: dict[str, str] = {}


def _cleanup_pods_on_exit():
    """Delete any pods we created, called on exit or signal."""
    for pod_name in _active_pods:
        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--wait=false"],
                capture_output=True, timeout=10, env=_cleanup_env or os.environ.copy(),
            )
        except Exception:
            pass
    _active_pods.clear()


atexit.register(_cleanup_pods_on_exit)


def _handle_signal(signum, frame):
    _cleanup_pods_on_exit()
    sys.exit(128 + signum)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)
RUNLLM = PROJECT_ROOT / "runllm"
DEFAULT_MODEL_DIR = "qwen2.5-1.5b"
RUNS_DIR = PROJECT_ROOT / "results" / "runs"
RESULTS_DIR = PROJECT_ROOT / "results"
PROGRESS_FILE = PROJECT_ROOT / "results" / "experiment_progress.json"

# After this many seconds, we inspect progress; if still in a long phase, abort and log.
INSPECT_AFTER_SEC = int(os.environ.get("EXPERIMENT_INSPECT_AFTER_SEC", "180"))

# If query count unchanged for this many seconds during benchmark, assume stuck and abort.
QUERY_STALE_SEC = int(os.environ.get("EXPERIMENT_QUERY_STALE_SEC", "30"))

# Timeout for sample query before benchmark (must complete or we abort)
SAMPLE_QUERY_TIMEOUT = int(os.environ.get("EXPERIMENT_SAMPLE_QUERY_TIMEOUT", "30"))

AGENT_MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "50"))

TOOL_SYSTEM_PROMPT = """\
You are a vLLM optimizer agent on Kubernetes (H200 GPU, CoreWeave).
Pick ONE simple change most likely to improve performance, then test it.

## Workflow
1. Read the leaderboard and lessons learned (in the prompt).
2. Pick one untried change. Do NOT bundle multiple changes.
3. Use read_file/read_logs to inspect past runs if needed; search_web/fetch_url for vLLM docs.
4. Write the config: write_file('vllm-config.yaml', <complete pod YAML>).
5. Optionally: run_benchmark(<description>) to deploy and test.

## Run policy
- One run = one experiment. After you benchmark a config, stop. Do NOT pivot to a second experiment in the same run.
- If the benchmark exposes a crash, invalid arg, startup bug, or harness/runtime issue, you may debug that SAME config idea.
- Do NOT turn a retry into a fresh optimization pass. Let the next run/agent try the next experiment.

## File safety
- write_file writes ONLY to the isolated per-run directory. You can only write 'vllm-config.yaml' and 'Makefile'.
- read_file can read from results/, runllm/, docs/, scripts/.

## Rules — DO NOT violate
- Do NOT change the model unless ALLOW_MODEL_CHANGE=1. Switching models is cheating, not optimizing.
- Do NOT game the benchmark (e.g. reducing max-model-len below workload needs, disabling production features). Goal is real-world speed improvement.
- Do NOT disable logging/stats flags (`--disable-log-stats`, `--disable-log-requests`). Logs and Prometheus metrics are essential for diagnosing performance — disabling them is a trivial micro-optimization that removes the data you need to find real improvements.

## Output format
Before writing config, state your strategy in 3-5 lines:
- What: `knob: old -> new`
- Why: 1-2 sentences grounded in evidence
- Expected effect: which metric improves and by roughly how much

If you determine no config change is needed, say NO_CONFIG_CHANGE: <reason> in your final message.
"""


def _metric(m: dict, k: str, sub: str = "successful") -> float | None:
    o = m.get(k, {})
    suc = o.get(sub) if isinstance(o, dict) else {}
    return suc.get("mean") if isinstance(suc, dict) else None


def _metric_pct(m: dict, k: str, pct: str, sub: str = "successful") -> float | None:
    o = m.get(k, {})
    suc = o.get(sub) if isinstance(o, dict) else {}
    if not isinstance(suc, dict):
        return None
    pcts = suc.get("percentiles", {})
    return pcts.get(pct) if isinstance(pcts, dict) else None


def _fmt_summary(m: dict) -> str:
    lat = _metric(m, "request_latency")
    ttft = _metric(m, "time_to_first_token_ms")
    tok = _metric(m, "tokens_per_second")
    rps = _metric(m, "requests_per_second")
    parts = []
    if lat is not None:
        parts.append(f"Latency: {lat*1000:.0f}ms")
    if ttft is not None:
        parts.append(f"TTFT: {ttft:.0f}ms")
    if tok is not None:
        parts.append(f"Throughput: {tok:.0f} tok/s")
    if rps is not None:
        parts.append(f"Req/s: {rps:.1f}")
    return " | ".join(parts) if parts else "—"


def _fmt_detail_lines(m: dict, run_dir: Path) -> list[str]:
    """Extra detail lines for leaderboard entries: percentiles + server-side metrics."""
    lines = []
    # Percentiles
    lat_p50 = _metric_pct(m, "request_latency", "p50")
    lat_p95 = _metric_pct(m, "request_latency", "p95")
    ttft_p50 = _metric_pct(m, "time_to_first_token_ms", "p50")
    ttft_p95 = _metric_pct(m, "time_to_first_token_ms", "p95")
    req_totals = m.get("request_totals", {})
    completed = req_totals.get("successful", req_totals.get("total", "?"))
    errored = req_totals.get("errored", 0)
    pct_parts = []
    if lat_p50 is not None and lat_p95 is not None:
        pct_parts.append(f"Latency p50={lat_p50*1000:.0f}ms p95={lat_p95*1000:.0f}ms")
    if ttft_p50 is not None and ttft_p95 is not None:
        pct_parts.append(f"TTFT p50={ttft_p50:.0f}ms p95={ttft_p95:.0f}ms")
    pct_parts.append(f"Completed={completed}")
    if errored:
        pct_parts.append(f"Errors={errored}")
    lines.append("  Detail: " + " | ".join(pct_parts))

    # Server-side metrics from vLLM /metrics
    vllm_summary = run_dir / "vllm_metrics_summary.json"
    if vllm_summary.exists():
        try:
            vs = json.loads(vllm_summary.read_text())
            server_parts = []
            preemptions = vs.get("vllm:num_preemptions_total")
            if preemptions is not None:
                server_parts.append(f"Preemptions={int(preemptions)}")
            gpu_cache = vs.get("vllm:gpu_cache_usage_perc")
            if gpu_cache is not None:
                server_parts.append(f"GPU-cache={gpu_cache:.1%}")
            cpu_cache = vs.get("vllm:cpu_cache_usage_perc")
            if cpu_cache is not None and cpu_cache > 0:
                server_parts.append(f"CPU-cache={cpu_cache:.1%}")
            if server_parts:
                lines.append("  Server: " + " | ".join(server_parts))
        except Exception:
            pass
    vllm_profile = run_dir / "vllm_metrics_profile.json"
    if vllm_profile.exists():
        try:
            profile = json.loads(vllm_profile.read_text())
            profile_summary = profile.get("summary", {})
            profile_parts = []
            gpu_cache_peak = profile_summary.get("gpu_cache_peak")
            if gpu_cache_peak is not None:
                profile_parts.append(f"GPU-cache-peak={gpu_cache_peak:.1%}")
            waiting_peak = profile_summary.get("waiting_peak")
            if waiting_peak is not None:
                profile_parts.append(f"Queue-peak={waiting_peak:.0f}")
            gpu_util_peak = profile_summary.get("gpu_utilization_peak")
            if gpu_util_peak is not None:
                profile_parts.append(f"GPU-util-peak={gpu_util_peak:.0f}%")
            if profile_parts:
                lines.append("  Profile: " + " | ".join(profile_parts))
        except Exception:
            pass
    return lines


def _get_sample_benchmark_data(runs_dir: Path | None = None) -> str:
    """Summarized benchmark data from runs in runs_dir (default: RUNS_DIR)."""
    base = runs_dir or RUNS_DIR
    if not base.exists():
        return "No previous benchmark data."
    runs = sorted(
        [d for d in base.iterdir() if d.is_dir() and (d / "benchmarks.json").exists()],
        key=lambda d: d.name,
        reverse=True,
    )[:5]
    lines = []
    for d in runs:
        try:
            data = json.loads((d / "benchmarks.json").read_text())
            b = data.get("benchmarks", [{}])[0]
            m = b.get("metrics", {})
            meta = {}
            if (d / "run_metadata.json").exists():
                meta = json.loads((d / "run_metadata.json").read_text())
            desc = meta.get("description", d.name)
            lines.append(f"- {d.name} ({desc}): {_fmt_summary(m)}")
        except Exception:
            pass
    return "\n".join(lines) if lines else "No valid benchmark data."


def _read_results_txt(results_path: Path | None = None) -> str:
    """Previous experiment summaries from results.txt."""
    path = results_path or (RESULTS_DIR / "results.txt")
    if not path.exists():
        return "No previous experiments."
    return path.read_text()[-8000:]  # last ~8k chars


def _collect_all_retros(runs_base: Path | None) -> str:
    """Collect all RETRO.md contents from run directories, newest first."""
    if not runs_base or not runs_base.exists():
        return ""
    retros = []
    for d in sorted(runs_base.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        retro_file = d / "RETRO.md"
        if retro_file.exists():
            try:
                content = retro_file.read_text().strip()
                if content:
                    retros.append(f"\n--- Retro from {d.name} ---\n{content}")
            except Exception:
                pass
    return "\n".join(retros) if retros else ""


def _get_latest_retro(runs_base: Path | None) -> tuple[str, str]:
    """Return (run_name, RETRO.md content) for the newest run that has one."""
    if not runs_base or not runs_base.exists():
        return "", ""
    for d in sorted(runs_base.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        retro_file = d / "RETRO.md"
        if retro_file.exists():
            try:
                content = retro_file.read_text().strip()
                if content:
                    return d.name, content
            except Exception:
                pass
    return "", ""


def _generate_full_retro(sweep_dir: Path, call_fn) -> str:
    """Synthesize all run retros into a single FULL_RETRO.txt for the sweep.

    Called before each improve run so the agent has a concise summary of
    everything learned so far.
    """
    raw_retros = _collect_all_retros(sweep_dir)
    if not raw_retros:
        return ""

    prompt = f"""Below are retrospectives from individual vLLM optimization runs in this sweep.
Synthesize them into a single concise document that a future AI agent will read before designing its next experiment.

Rules:
- Deduplicate: if multiple retros say the same thing, state it once.
- Organize by theme (e.g. "attention backends", "memory settings", "compilation", "decode vs prefill").
- For each insight, include the specific knob values and metrics that support it.
- Flag anything that crashed or produced errors, and how to avoid it.
- End with a short "What to try next" section: 2-3 concrete, untested ideas ranked by expected impact.
- Be terse. No filler. Target 20-40 lines.

Raw retros:
{raw_retros}"""

    try:
        result = call_fn(prompt)
        return result.strip()
    except Exception as e:
        return f"(Failed to generate synthesis: {e})\n\n{raw_retros[:3000]}"


def _extract_vllm_args(config_text: str) -> str:
    """Extract just the image and arg list from a vLLM pod YAML."""
    try:
        data = yaml.safe_load(config_text) or {}
    except Exception:
        return ""
    containers = (((data.get("spec") or {}).get("containers")) or [])
    if not containers:
        return ""
    container = containers[0] or {}
    image = str(container.get("image", "")).strip()
    args_list = []
    args = container.get("args") or []
    idx = 0
    while idx < len(args):
        item = str(args[idx]).strip()
        if item.startswith("--"):
            if idx + 1 < len(args) and not str(args[idx + 1]).strip().startswith("--"):
                args_list.append(f"{item} {str(args[idx + 1]).strip()}")
                idx += 2
                continue
            args_list.append(item)
        idx += 1
    return f"image={image}  args: {', '.join(args_list)}" if args_list else f"image={image}"


def _extract_config_state(config_text: str) -> dict[str, str | bool]:
    """Extract image, args, and env vars from the pod YAML for diffing."""
    state: dict[str, str | bool] = {}
    try:
        data = yaml.safe_load(config_text) or {}
    except Exception:
        return state
    containers = (((data.get("spec") or {}).get("containers")) or [])
    if not containers:
        return state
    container = containers[0] or {}
    image = container.get("image")
    if image:
        state["image"] = str(image).strip()

    args = container.get("args") or []
    idx = 0
    while idx < len(args):
        key = str(args[idx]).strip()
        if key.startswith("--"):
            state[f"arg:{key}"] = True
            if idx + 1 < len(args) and not str(args[idx + 1]).strip().startswith("--"):
                state[f"arg:{key}"] = str(args[idx + 1]).strip()
                idx += 2
                continue
        idx += 1

    for env_var in container.get("env") or []:
        name = str(env_var.get("name", "")).strip()
        if not name:
            continue
        if "value" in env_var:
            state[f"env:{name}"] = str(env_var["value"]).strip()
        elif "valueFrom" in env_var:
            state[f"env:{name}"] = "(valueFrom)"
        else:
            state[f"env:{name}"] = "(set)"
    return state


def _format_state_value(value: str | bool | None) -> str:
    if value is True:
        return "enabled"
    if value in (None, ""):
        return "absent"
    return str(value)


def _summarize_config_changes(config_text: str, reference_text: str | None) -> list[str]:
    """Summarize config changes relative to a reference config."""
    if not config_text or not reference_text:
        return []
    current = _extract_config_state(config_text)
    reference = _extract_config_state(reference_text)
    changes = []
    for key in sorted(set(current) | set(reference)):
        before = reference.get(key)
        after = current.get(key)
        if before == after:
            continue
        if key == "image":
            label = "image"
        elif key.startswith("arg:"):
            label = key[4:]
        elif key.startswith("env:"):
            label = f"env {key[4:]}"
        else:
            label = key
        changes.append(f"{label}: {_format_state_value(before)} -> {_format_state_value(after)}")
    return changes


def _extract_no_config_change_reason(text: str) -> str | None:
    m = re.search(r"NO_CONFIG_CHANGE:\s*(.+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _get_experiment_leaderboard(runs_base: Path, project_root: Path) -> str:
    """Compact leaderboard ranked according to the sweep objective."""
    if not runs_base.exists():
        return "No experiments."
    dirs = [d for d in runs_base.iterdir() if d.is_dir() and not d.name.startswith(".")]
    sweep_name = runs_base.name.replace("sweep-", "")
    objective = sweep_objective(sweep_name)
    reference_config_text = None
    for cfg in ("baseline/vllm_config.yaml", "baseline/runllm/vllm-config.yaml", "baseline/runllm/vllm-qwen.yaml"):
        fp = runs_base / cfg
        if fp.exists():
            reference_config_text = fp.read_text()
            break

    successes = []
    failures = []
    for d in dirs:
        meta = {}
        if (d / "run_metadata.json").exists():
            try:
                meta = json.loads((d / "run_metadata.json").read_text())
            except Exception:
                pass
        desc = meta.get("description", "")
        short_name = _read_short_name(d)
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                if not is_valid_run(d, data):
                    n_completed = completed_request_count(data)
                    failures.append({
                        "name": d.name,
                        "desc": desc,
                        "result": f"insufficient benchmark traffic: only {n_completed} requests completed",
                        "changes": _summarize_config_changes(
                            next((fp.read_text() for cfg in ("vllm_config.yaml", "runllm/vllm-config.yaml", "runllm/vllm-qwen.yaml")
                                  if (fp := d / cfg).exists()), ""),
                            reference_config_text,
                        ),
                    })
                    continue
                b = data.get("benchmarks", [{}])[0]
                m = b.get("metrics", {})
                metrics = _fmt_summary(m)
                if metrics and metrics != "—":
                    config_text = ""
                    for cfg in ("vllm_config.yaml", "runllm/vllm-config.yaml", "runllm/vllm-qwen.yaml"):
                        fp = d / cfg
                        if fp.exists():
                            config_text = fp.read_text()
                            break
                    lat = metric_mean(m, "request_latency")
                    tok = metric_mean(m, "tokens_per_second")
                    ttft = metric_mean(m, "time_to_first_token_ms")
                    successes.append({"name": d.name, "short_name": short_name, "metrics": metrics, "desc": desc,
                                      "config_summary": _extract_vllm_args(config_text) if config_text else "",
                                      "changes": _summarize_config_changes(config_text, reference_config_text),
                                      "latency": lat or 999,
                                      "throughput": tok or 0,
                                      "ttft": ttft or 999999,
                                      "detail_lines": _fmt_detail_lines(m, d),
                                      "path": str(d.relative_to(project_root))})
                    continue
            except Exception:
                pass
        # Failed or no metrics
        result = ""
        config_text = ""
        for cfg in ("vllm_config.yaml", "runllm/vllm-config.yaml", "runllm/vllm-qwen.yaml"):
            fp = d / cfg
            if fp.exists():
                config_text = fp.read_text()
                break
        if (d / "run_metadata.json").exists():
            try:
                rm = json.loads((d / "run_metadata.json").read_text())
                result = rm.get("result", "")
            except Exception:
                pass
        if desc or result:
            failures.append({
                "name": d.name,
                "desc": desc,
                "result": result,
                "changes": _summarize_config_changes(config_text, reference_config_text),
            })

    if objective == "throughput":
        successes.sort(key=lambda x: (-x["throughput"], x["latency"]))
    elif objective == "ttft":
        successes.sort(key=lambda x: x["ttft"])
    else:
        successes.sort(key=lambda x: x["latency"])

    lines = []
    if successes:
        lines.append(f"LEADERBOARD (successful runs, ranked by {sweep_ranking_label(sweep_name)}):")
        lines.append("-" * 100)
        for s in successes:
            header = s["name"]
            if s.get("short_name"):
                header += f"  [{s['short_name']}]"
            lines.append(f"{header}  {s['metrics']}")
            lines.append("")

    if failures:
        lines.append(f"\nFailed runs ({len(failures)} total — DO NOT repeat these strategies):")
        for f in failures[-20:]:
            err_brief = f['result'][:120] if f['result'] else "no details"
            lines.append(f"  {f['name']}: {f['desc'][:100]}  — {err_brief}")

    lines.append(f"\nTo get details on any run, use: read_file('results/{runs_base.name}/<run>/RETRO.md') or read_logs('<run>', 'benchmark')")

    return "\n".join(lines) if lines else "No experiments yet."


def _write_leaderboard_to_sweep(sweep_dir: Path) -> None:
    """Write the current leaderboard to sweep_dir/leaderboard.txt for easy viewing."""
    if not sweep_dir or not sweep_dir.exists():
        return
    leaderboard = _get_experiment_leaderboard(sweep_dir, PROJECT_ROOT)
    (sweep_dir / "leaderboard.txt").write_text(leaderboard)


def _summarize_profile_json(profile: dict) -> str:
    summary = profile.get("summary", {}) if isinstance(profile, dict) else {}
    parts = []
    gpu_cache_peak = summary.get("gpu_cache_peak")
    if gpu_cache_peak is not None:
        parts.append(f"gpu_cache_peak={gpu_cache_peak:.1%}")
    waiting_peak = summary.get("waiting_peak")
    if waiting_peak is not None:
        parts.append(f"queue_peak={waiting_peak:.0f}")
    running_peak = summary.get("running_peak")
    if running_peak is not None:
        parts.append(f"running_peak={running_peak:.0f}")
    gen_peak = summary.get("generation_throughput_peak")
    if gen_peak is not None:
        parts.append(f"gen_tps_peak={gen_peak:.0f}")
    gpu_util_peak = summary.get("gpu_utilization_peak")
    if gpu_util_peak is not None:
        parts.append(f"gpu_util_peak={gpu_util_peak:.0f}%")
    preempt_delta = summary.get("preemptions_delta")
    if preempt_delta:
        parts.append(f"preemptions_delta={preempt_delta:.0f}")
    hints = profile.get("diagnosis_hints", [])
    if hints:
        parts.append("hints=" + ",".join(hints[:3]))
    return " | ".join(parts)


def _get_profile_context(runs_base: Path, project_root: Path) -> str:
    """Compact summaries from recent profile artifacts for prompt context."""
    if not runs_base.exists():
        return ""
    lines = []
    profiled_runs = sorted(
        [
            d for d in runs_base.iterdir()
            if d.is_dir() and not d.name.startswith(".") and (d / "vllm_metrics_profile.json").exists()
        ],
        key=lambda d: d.name,
        reverse=True,
    )[:5]
    for d in profiled_runs:
        try:
            profile = json.loads((d / "vllm_metrics_profile.json").read_text())
            summary = _summarize_profile_json(profile)
            if not summary:
                continue
            rel = d.relative_to(project_root)
            lines.append(f"- {d.name}: {summary}. Details: read_file('{rel}/vllm_metrics_profile.json')")
        except Exception:
            continue
    if not lines:
        return ""
    return "## Hardware/profile signals from recent runs\n\n" + "\n".join(lines) + "\n"


def _describe_hardware(vllm_yaml_text: str) -> str:
    try:
        doc = yaml.safe_load(vllm_yaml_text) or {}
        container = ((doc.get("spec") or {}).get("containers") or [{}])[0]
        limits = (container.get("resources") or {}).get("limits") or {}
        gpu_count = limits.get("nvidia.com/gpu")
        if gpu_count:
            return f"{gpu_count}x NVIDIA H200 GPU"
    except Exception:
        pass
    return "NVIDIA H200 GPU"


def _get_best_config_yaml(runs_base: Path) -> str | None:
    """Get the full YAML of the best successful run for reference."""
    if not runs_base.exists():
        return None
    best_dir = None
    best_lat = 999.0
    for d in runs_base.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                m = data.get("benchmarks", [{}])[0].get("metrics", {})
                lat = _metric(m, "request_latency")
                if lat is not None and lat < best_lat:
                    best_lat = lat
                    best_dir = d
            except Exception:
                pass
    if best_dir:
        for cfg in ("vllm_config.yaml", "runllm/vllm-config.yaml", "runllm/vllm-qwen.yaml"):
            fp = best_dir / cfg
            if fp.exists():
                return fp.read_text()[:2000]
    return None


def _get_workload_description(runs_base: Path) -> str:
    """Extract benchmark workload info (prompt tokens, output tokens, profile) from a benchmarks.json."""
    for d in sorted(runs_base.iterdir(), key=lambda x: x.name, reverse=True) if runs_base.exists() else []:
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                a = data.get("args", {})
                b = data.get("benchmarks", [{}])[0]
                cfg = b.get("config", {})
                strat = cfg.get("strategy", {}).get("type_", a.get("profile", "unknown"))
                max_req = a.get("max_requests", "?")
                max_sec = a.get("max_seconds", "?")
                data_info = a.get("data", ["?"])
                return f"Profile: {strat}, max_requests={max_req}, max_seconds={max_sec}, data={data_info}"
            except Exception:
                pass
    return "unknown"


def _call_anthropic(prompt: str, model: str) -> str:
    from anthropic import Anthropic
    msg = Anthropic().messages.create(model=model, max_tokens=8192, messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text if msg.content else ""


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI()
    if "codex" in model.lower():
        r = client.responses.create(model=model, max_output_tokens=8192, input=[{"role": "user", "content": prompt}])
        return r.output_text if hasattr(r, "output_text") and r.output_text else ""
    r = client.chat.completions.create(model=model, max_tokens=8192, messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content if r.choices else ""


def _generate_short_name(description: str, result: str, call_fn) -> str:
    """Ask the LLM for a 3-6 word descriptive name for this run."""
    prompt = (
        "Give a short descriptive name (3-6 words, no quotes, no punctuation) for this vLLM optimization experiment.\n\n"
        f"Strategy: {description[:500]}\n"
        f"Result: {result[:200]}\n\n"
        "Reply with ONLY the short name, nothing else. Examples: 'flashinfer + larger batches', 'prefix caching disabled', 'fp8 kv cache', 'baseline config'"
    )
    try:
        name = call_fn(prompt).strip().strip('"\'').strip()
        if len(name) > 60:
            name = name[:60].rsplit(" ", 1)[0]
        return name
    except Exception:
        return ""


def _save_short_name(run_dir: Path, name: str) -> None:
    if name:
        (run_dir / "short_name.txt").write_text(name)


def _read_short_name(run_dir: Path) -> str:
    f = run_dir / "short_name.txt"
    if f.exists():
        try:
            return f.read_text().strip()
        except Exception:
            pass
    return ""


def _extract_code_block(text: str, lang: str = "") -> str | None:
    pattern = rf"```(?:{re.escape(lang)})?\s*\n(.*?)```" if lang else r"```\w*\s*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_yaml(text: str) -> str | None:
    for lang in ("yaml", "yml", ""):
        found = _extract_code_block(text, lang)
        if found and ("apiVersion:" in found or "kind:" in found):
            return found
    return None


def _extract_makefile(text: str) -> str | None:
    found = _extract_code_block(text, "makefile")
    if found:
        return found
    found = _extract_code_block(text, "Makefile")
    if found:
        return found
    return None


def _write_progress(phase: str, extra: dict | None = None) -> None:
    """Write current phase to progress file for inspection."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "phase": phase,
        "phase_started": datetime.now().isoformat(),
        "pid": os.getpid(),
    }
    if extra:
        data.update(extra)
    PROGRESS_FILE.write_text(json.dumps(data, indent=2))


def _log_run(run_dir: Path, msg: str, also_stdout: bool = True) -> None:
    """Append to run_dir/run.log and optionally print."""
    if run_dir:
        log_file = run_dir / "run.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    if also_stdout:
        print(msg)


def _elapsed_since(start: float) -> float:
    return time.time() - start


def _extract_description(text: str) -> str:
    # Fallback when agent doesn't provide summary
    m = re.search(r"(?:description|experiment|strategy):\s*(.+?)(?:```|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    return text[:300].strip()


def _ask_agent_summary(response: str, call_fn) -> str:
    """Ask agent for a concise 2-4 sentence summary of its proposal. Used for terminal display."""
    try:
        summary = call_fn(f"""You just proposed a vLLM config change. Here is your response:

{response[:4000]}

In 2-4 sentences, summarize: what you're changing and why it should help. Output only the summary, nothing else. Be concise for terminal display.""")
        return summary.strip() if summary else ""
    except Exception:
        return ""


def _check_abort(start: float, phase: str, last_progress: float | None = None) -> str | None:
    """Return abort message if we should abort, unless recent progress was made."""
    if INSPECT_AFTER_SEC <= 0:
        return None
    if _elapsed_since(start) < INSPECT_AFTER_SEC:
        return None
    if last_progress is not None and (time.time() - last_progress) < INSPECT_AFTER_SEC:
        return None
    return f"Aborted after {INSPECT_AFTER_SEC}s: stuck in phase '{phase}'"


# Patterns indicating infrastructure/Kubernetes setup errors (NOT fixable by changing vLLM YAML)
INFRASTRUCTURE_ERROR_PATTERNS = [
    "Forbidden",
    "Error from server (Forbidden)",
    "connection refused",
    "dial tcp",
    "RBAC",
    "Unauthorized",
    "get current server API",
]


def _is_infrastructure_error(result: str) -> bool:
    """Return True if the error is kubectl/K8s setup, not vLLM config."""
    r = result.lower()
    return any(p.lower() in r for p in INFRASTRUCTURE_ERROR_PATTERNS)


# Patterns that indicate vLLM failed to start (fatal config error, crash, etc.)
VLLM_FATAL_LOG_PATTERNS = [
    (re.compile(r"vllm: error: unrecognized arguments?", re.I), "unrecognized vLLM arguments"),
    (re.compile(r"error: (?:invalid|unsupported|unknown)", re.I), "invalid/unsupported option"),
    (re.compile(r"Traceback \(most recent call last\)", re.I), "Python traceback"),
    (re.compile(r"ModuleNotFoundError|ImportError", re.I), "import error"),
    (re.compile(r"RuntimeError:", re.I), "runtime error"),
    (re.compile(r"CUDA (?:out of memory|error)", re.I), "CUDA OOM/error"),
    (re.compile(r"exit code [1-9]\d*", re.I), "non-zero exit"),
]


def _find_free_port() -> int:
    """Find a free local port for port-forwarding."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _k8s_label_value(value: str) -> str:
    """Sanitize a value for Kubernetes labels."""
    value = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower())
    value = value.strip("-.")
    return value[:63] or "default"


def _rewrite_pod_name(yaml_path: Path, new_name: str, sweep: str | None = None) -> None:
    """Rewrite metadata.name and add labels for sweep discovery."""
    text = yaml_path.read_text()
    text = re.sub(r'(metadata:\s*\n\s*name:\s*)(\S+)', rf'\g<1>{new_name}', text)
    labels = {"autollm-managed": "true"}
    if sweep:
        labels["autollm-sweep"] = _k8s_label_value(sweep)
    quoted_labels = {k: json.dumps(v) for k, v in labels.items()}
    label_lines = "\n".join(f"    {k}: {v}" for k, v in quoted_labels.items())
    if re.search(r"metadata:\s*\n(?:\s+.+\n)*?\s+labels:\s*\n", text):
        for key, value in quoted_labels.items():
            pattern = rf"(metadata:\s*\n(?:\s+.+\n)*?\s+labels:\s*\n)"
            if re.search(rf"^\s+{re.escape(key)}:\s*", text, re.MULTILINE):
                text = re.sub(rf"(^\s+{re.escape(key)}:\s*).*$", rf"\1{value}", text, flags=re.MULTILINE)
            else:
                text = re.sub(pattern, rf"\1    {key}: {value}\n", text, count=1)
    else:
        text = re.sub(
            r"(metadata:\s*\n\s*name:\s*\S+\n)",
            rf"\1  labels:\n{label_lines}\n",
            text,
            count=1,
        )
    yaml_path.write_text(text)


def _fetch_and_check_logs(run_dir: Path, env: dict, logs_file: Path, pod_name: str = "vllm") -> str | None:
    """Fetch kubectl logs, append to logs_file, return error msg if fatal pattern found."""
    try:
        r = subprocess.run(
            ["kubectl", "logs", pod_name, "--all-containers=true", "--tail=200"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode != 0:
            return None
        text = (r.stdout or "") + (r.stderr or "")
        if not text.strip():
            return None
        with open(logs_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            f.write(text)
        for pat, label in VLLM_FATAL_LOG_PATTERNS:
            m = pat.search(text)
            if m:
                snippet = text[max(0, m.start() - 50) : m.end() + 150]
                return f"vLLM logs show {label}: {snippet[:300].strip()!r}"
    except Exception:
        pass
    return None


def _deploy_and_benchmark(
    experiment_dir: Path, benchmark: str, run_dir: Path, ts: str, sweep: str | None = None
) -> tuple[bool, str]:
    """Deploy from experiment_dir, run benchmark, stream logs to run_dir, track queries, abort if stuck.
    Uses a unique pod name and local port so multiple runs can execute in parallel."""
    start = time.time()
    vllm_yaml = experiment_dir / "vllm-config.yaml"
    env = os.environ.copy()
    env["VLLM_CONFIG"] = str(vllm_yaml)
    env["KUBECONFIG"] = os.environ.get("KUBECONFIG", "")
    pf = None
    bench_proc = None
    logs_proc = None
    profiler: VLLMProfiler | None = None

    # Unique pod name and port for parallel runs
    short_id = ts.replace("_", "")[-8:]  # e.g. "12112142" from "20260312_112142"
    base_pod = "vllm"
    try:
        _doc = yaml.safe_load(vllm_yaml.read_text())
        base_pod = _doc.get("metadata", {}).get("name", "vllm") or "vllm"
    except Exception:
        pass
    pod_name = f"{base_pod}-{short_id}"
    local_port = _find_free_port()
    _rewrite_pod_name(vllm_yaml, pod_name, sweep=sweep)
    _log_run(run_dir, f"Pod: {pod_name}, local port: {local_port}")

    # Register for cleanup on Ctrl+C / crash
    _active_pods.append(pod_name)
    _cleanup_env.update(env)

    run_dir.mkdir(parents=True, exist_ok=True)

    def _append_deploy_log(cmd: list, r: subprocess.CompletedProcess) -> None:
        with open(run_dir / "deploy.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {' '.join(cmd)} ---\n")
            f.write(f"returncode={r.returncode}\n")
            if r.stdout:
                f.write(r.stdout[:2000] + ("..." if len(r.stdout) > 2000 else "") + "\n")
            if r.stderr:
                f.write("STDERR: " + r.stderr[:1000] + "\n")

    def _cleanup(msg: str | None = None) -> tuple[bool, str] | None:
        nonlocal profiler
        if profiler is not None:
            try:
                profiler.stop()
            except Exception:
                pass
            try:
                write_vllm_snapshot(pod_name, run_dir, env)
            except Exception:
                pass
            profiler = None
        for proc in (logs_proc, bench_proc, pf):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true"],
                capture_output=True, timeout=30, env=env,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--force", "--grace-period=0"],
                capture_output=True, timeout=30, env=env,
            )
        if pod_name in _active_pods:
            _active_pods.remove(pod_name)
        if msg:
            _write_progress("aborted", {"reason": msg})
            _log_run(run_dir, f"ABORTED: {msg}")
            return False, msg
        return None

    _write_progress("deploy_delete", {"experiment_dir": str(experiment_dir), "run_dir": str(run_dir), "pod_name": pod_name})
    _log_run(run_dir, "Deploy: delete + apply")

    for cmd, err in [
        (["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true"], "delete failed"),
        (["kubectl", "apply", "-f", str(vllm_yaml)], "apply failed"),
    ]:
        if m := _check_abort(start, "deploy"):
            return _cleanup(m)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        except subprocess.TimeoutExpired:
            if "delete" in cmd:
                # Force-delete on timeout and continue to apply
                subprocess.run(
                    ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--force", "--grace-period=0"],
                    capture_output=True, text=True, timeout=30, env=env,
                )
                continue
            _cleanup()
            return False, f"{err}: timed out after 120s"
        _append_deploy_log(cmd, r)
        if r.returncode != 0:
            _cleanup()
            return False, f"{err}: {(r.stderr or r.stdout or '').strip()[:500]}"

    kubectl_logs_file = run_dir / "kubectl_logs.txt"
    kubectl_logs_file.write_text(f"--- logs started {datetime.now().isoformat()} ---\n")

    _write_progress("pod_wait", {})
    _log_run(run_dir, "Waiting for pod Ready...")
    for _ in range(20):
        if m := _check_abort(start, "pod_wait"):
            return _cleanup(m)
        if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
            return _cleanup(f"vLLM startup error (pod_wait): {err}")
        r = subprocess.run(
            ["kubectl", "wait", "--for=condition=Ready", f"pod/{pod_name}", "--timeout=30s"],
            capture_output=True, text=True, env=env,
        )
        _append_deploy_log(["kubectl", "wait", "..."], r)
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        return _cleanup(f"Pod not ready: {(r.stderr or r.stdout or '').strip()[:500]}")

    _write_progress("health_check", {})
    _log_run(run_dir, "Waiting for vLLM health...")
    health_start = time.time()
    for i in range(900):
        if m := _check_abort(start, "health_check"):
            return _cleanup(m)
        if i % 5 == 4:
            if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
                return _cleanup(f"vLLM startup error (health_check): {err}")
        r = subprocess.run(
            ["kubectl", "exec", pod_name, "--", "curl", "-sf", "--max-time", "3", "http://localhost:8000/health"],
            capture_output=True, timeout=5, env=env,
        )
        if r.returncode == 0:
            _log_run(run_dir, f"vLLM ready ({time.time() - health_start:.0f}s)")
            break
        time.sleep(2)
    else:
        return _cleanup("vLLM did not become ready (health check timeout after 30 min)")

    _write_progress("sample_query", {})
    _log_run(run_dir, "Running sample query...")
    model = "Qwen/Qwen2.5-1.5B-Instruct"
    try:
        text = vllm_yaml.read_text()
        m = re.search(r'--served-model-name\s+([^\s\\]+)', text)
        if not m:
            m = re.search(r'--model["\']?\s*\n\s*-\s*["\']?([^"\'"\n\r]+)', text)
        if m:
            model = m.group(1).strip().rstrip("'\"")
    except Exception:
        pass
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 16,
    })
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "--", "curl", "-sf", "-X", "POST", "http://localhost:8000/v1/chat/completions",
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=SAMPLE_QUERY_TIMEOUT, env=env,
    )
    _append_deploy_log(["kubectl", "exec", pod_name, "--", "curl", "...", "sample query"], r)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:500]
        _cleanup()
        return False, f"Sample query failed (exit {r.returncode}): {err}"
    try:
        data = json.loads(r.stdout or "{}")
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content or not isinstance(content, str):
            _cleanup()
            return False, "Sample query returned empty or invalid response"
    except json.JSONDecodeError:
        _cleanup()
        return False, "Sample query returned invalid JSON"
    _log_run(run_dir, "Sample query OK (model responded)")
    profiler = VLLMProfiler(
        pod_name=pod_name,
        run_dir=run_dir,
        env=env,
        yaml_path=vllm_yaml,
        interval_sec=float(os.environ.get("VLLM_PROFILE_INTERVAL_SEC", "5")),
        log_fn=lambda msg: _log_run(run_dir, msg),
    )
    profiler.start()

    _write_progress("port_forward", {})
    pf = subprocess.Popen(
        ["kubectl", "port-forward", pod_name, f"{local_port}:8000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    time.sleep(2)

    with open(kubectl_logs_file, "a", encoding="utf-8") as f:
        f.write(f"\n--- live stream started {datetime.now().isoformat()} ---\n")
    logs_proc = subprocess.Popen(
        ["kubectl", "logs", "-f", pod_name, "--all-containers=true"],
        stdout=open(kubectl_logs_file, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=env,
    )

    timeout_sec = 3600  # generous max; real timeout is QUERY_STALE_SEC (no progress for 30s)

    _write_progress("benchmark", {"timeout_sec": timeout_sec, "run_dir": str(run_dir)})
    _log_run(run_dir, f"Starting benchmark ({benchmark}), run_dir={run_dir}")

    bench_env = env.copy()
    bench_env["EXPERIMENT_RUN_DIR"] = str(run_dir)
    bench_env["EXPERIMENT_BENCHMARK"] = benchmark
    bench_env["EXPERIMENT_DESCRIPTION"] = f"ai_experiment {experiment_dir.name}"
    bench_env["EXPERIMENT_TARGET"] = f"http://localhost:{local_port}"

    guideline_script = PROJECT_ROOT / "scripts" / "run_guideline_experiment.py"
    bench_proc = subprocess.Popen(
        [sys.executable, str(guideline_script)],
        cwd=str(PROJECT_ROOT),
        env=bench_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    harness_out = run_dir / "harness_output.txt"
    last_queries = -1
    last_updated = time.time()
    last_wait_report = 0.0
    query_progress_file = run_dir / "query_progress.json"
    max_requests = BENCHMARK_MAX_REQUESTS.get(benchmark, 0)
    bench_start = time.time()
    last_harness_line = ""

    def _count_from_kubectl_logs() -> int:
        """Count actual chat completion requests (not health checks or model list)."""
        if not kubectl_logs_file.exists():
            return 0
        try:
            text = kubectl_logs_file.read_text(errors="replace")
            return len(re.findall(r"POST /v1/chat/completions.* 200", text))
        except Exception:
            return 0

    stdout_lines: list[str] = []

    def _read_stdout():
        if bench_proc.stdout:
            for line in bench_proc.stdout:
                stdout_lines.append(line)

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()

    try:
        with open(harness_out, "w", encoding="utf-8") as out:
            poll_interval = 10
            while True:
                ret = bench_proc.poll()
                if ret is not None:
                    reader.join(timeout=2)
                    out.write("".join(stdout_lines))
                    if last_queries > 0:
                        print()  # newline after progress bar
                    break

                while stdout_lines:
                    line = stdout_lines.pop(0)
                    out.write(line)
                    out.flush()
                    stripped = line.strip()
                    if stripped:
                        last_harness_line = stripped
                        print(f"  [guidellm] {stripped}", flush=True)

                queries = last_queries
                if query_progress_file.exists():
                    try:
                        d = json.loads(query_progress_file.read_text())
                        queries = d.get("queries_completed", 0)
                    except Exception:
                        pass
                if queries <= 0:
                    queries = _count_from_kubectl_logs()

                now = time.time()
                if queries > last_queries:
                    last_queries = queries
                    last_updated = now
                    last_wait_report = now
                    _write_progress("benchmark", {
                        "timeout_sec": timeout_sec,
                        "run_dir": str(run_dir),
                        "queries_completed": last_queries,
                        "last_progress": datetime.now().isoformat(),
                    })
                    # Progress bar
                    elapsed = now - bench_start
                    if max_requests > 0 and last_queries > 0:
                        pct = min(last_queries / max_requests, 1.0)
                        bar_width = 30
                        filled = int(bar_width * pct)
                        bar = "█" * filled + "░" * (bar_width - filled)
                        rate = last_queries / elapsed if elapsed > 0 else 0
                        eta = (max_requests - last_queries) / rate if rate > 0 else 0
                        print(f"\r  [{bar}] {last_queries}/{max_requests} requests ({pct*100:.0f}%) | {rate:.1f} req/s | ETA {eta:.0f}s", end="", flush=True)
                    else:
                        print(f"\r  {last_queries} requests | {elapsed:.0f}s elapsed", end="", flush=True)
                elif (now - last_updated) >= min(10, QUERY_STALE_SEC) and (now - last_wait_report) >= 10:
                    last_wait_report = now
                    wait_for = int(now - last_updated)
                    last_line = last_harness_line[:200] if last_harness_line else "(no harness output yet)"
                    print(
                        f"\n  Waiting for benchmark progress: {queries} completed requests, no update for {wait_for}s",
                        flush=True,
                    )
                    print(f"  Last guidellm output: {last_line}", flush=True)
                elif (now - last_updated) >= QUERY_STALE_SEC:
                    if (run_dir / "benchmarks.json").exists():
                        _log_run(run_dir, "Benchmark output found despite stale query count")
                        if last_queries > 0:
                            print()
                        break
                    if last_queries > 0:
                        print()
                    if last_harness_line:
                        print(f"  Last guidellm output before abort: {last_harness_line[:200]}", flush=True)
                    return _cleanup(
                        f"Query count unchanged at {queries} for {QUERY_STALE_SEC}s (no progress)"
                    )

                if _elapsed_since(start) >= timeout_sec:
                    if last_queries > 0:
                        print()
                    return _cleanup(f"Benchmark timed out after {timeout_sec}s")
                if m := _check_abort(start, "benchmark", last_progress=last_updated):
                    return _cleanup(m)

                time.sleep(min(poll_interval, 2))

        r = subprocess.CompletedProcess(bench_proc.args, bench_proc.returncode, None, None)
    except Exception as e:
        return _cleanup(f"Benchmark error: {e}")
    finally:
        for proc in (logs_proc, pf):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    if r.returncode != 0:
        _cleanup()
        return False, f"Benchmark failed (exit {r.returncode}). See {run_dir}/harness_output.txt"

    _write_progress("done", {})
    _log_run(run_dir, "Benchmark complete")

    if profiler is not None:
        profiler.stop()
        profiler = None

    # Scrape vLLM Prometheus metrics while pod is still alive
    write_vllm_snapshot(pod_name, run_dir, env)

    benchmarks_json = run_dir / "benchmarks.json"
    if not benchmarks_json.exists() and (run_dir / "benchmark.json").exists():
        shutil.copy(run_dir / "benchmark.json", benchmarks_json)

    if (run_dir / "benchmarks.json").exists():
        try:
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"), str(run_dir)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    # Clean up pod after successful benchmark
    _cleanup()

    benchmarks_json = run_dir / "benchmarks.json"
    if benchmarks_json.exists():
        try:
            data = json.loads(benchmarks_json.read_text())
            b = data.get("benchmarks", [{}])[0]
            m = b.get("metrics", {})
            return True, _fmt_summary(m)
        except Exception:
            pass
    return True, "Benchmark completed (no metrics extracted)"


def _write_run_retro(
    *, run_dir: Path, experiment_dir: Path, description: str,
    result: str, success: bool, attempt: int, max_attempts: int,
    provider: str, model: str, sweep_dir: Path | None, sweep: str | None,
    benchmark: str, ts: str, call_fn,
) -> None:
    """Write a short RETRO.md for every run — success or failure."""
    outcome = "succeeded" if success else "failed"
    try:
        profile_rel = run_dir.relative_to(PROJECT_ROOT)
        profile_hint = f"read_file('{profile_rel}/vllm_metrics_profile.json')"
    except Exception:
        profile_hint = "read the local vllm_metrics_profile.json"
    retro_prompt = f"""Write a RETRO.md for this vLLM optimization run that {outcome}.

**Strategy:** {description[:500]}
**Result:** {result[:300]}
**Attempt:** {attempt}/{max_attempts}
**Run directory:** {run_dir.name}

Use read_logs('{run_dir.name}', 'benchmark') to check the benchmark data if available.
Use read_logs('{run_dir.name}', 'deploy') or read_logs('{run_dir.name}', 'kubectl') for deploy/runtime details.
If profiling data exists, use {profile_hint} to inspect hardware/cache/queue signals.

Write a RETRO.md (in a ```markdown block```). Be as brief as possible — no filler, no boilerplate.
The audience is a future AI agent that will read this before designing the next experiment.
Include ANYTHING that helps that agent avoid pitfalls or design a better run:

- Treat the final outcome of this run as authoritative. If the overall run succeeded, the
  **Result** section must lead with the final successful benchmark metrics, even if earlier
  attempts in the same run directory failed. Mention earlier failed attempts under
  **Crashes / errors**, not as the main result.

- **Change:** what knob(s) were changed, from what to what (exact values)
- **Result:** key metrics (throughput, latency, TTFT) or the specific error. Numbers only, skip prose.
- **Why it worked / failed:** the causal explanation, not just a restatement of the result
- **Crashes / errors:** if the LLM, benchmark tool, deploy, or any other step crashed or
  errored at any point during this run, note what happened and how to avoid it.
  Check deploy logs and kubectl logs for OOMs, timeouts, pod evictions, etc.
- **Research findings:** if web search, docs, or log analysis revealed useful vLLM knowledge
  during the research phase (e.g. version-specific behavior, undocumented defaults,
  interactions between flags), capture it here even if it wasn't directly tested.
- **Hardware/profile evidence:** when available, include the important profile facts
  (queue peak, GPU KV cache peak, GPU utilization peak, preemption delta, diagnosis hints)
  if they help explain the outcome or suggest the next knob to try.
- **Pitfall or insight:** anything non-obvious that a future agent should know
  (e.g. "gpu-memory-utilization above 0.95 causes OOM on H200 with this model",
   "enabling chunked-prefill hurt throughput at low concurrency",
   "this arg is silently ignored in vLLM 0.7.x",
   "benchmark timed out because pod took 4min to load model — increase wait")

Skip sections that have nothing useful to say. Aim for 3-10 lines — terse but complete."""
    try:
        retro_ctx = ToolContext(
            project_root=PROJECT_ROOT, experiment_dir=experiment_dir,
            run_dir=run_dir, sweep_dir=sweep_dir, sweep=sweep or None,
            benchmark=benchmark, ts=ts, env=os.environ.copy(),
            log_path=run_dir / "retro_agent.log",
        )
        retro_result = run_agent(
            "You write terse, high-signal retrospectives for vLLM optimization runs. A future AI agent will read this to plan better experiments. No filler. Use tools to get exact numbers.",
            retro_prompt, provider, model, retro_ctx, max_turns=10,
        )
        retro_content = retro_result.text
    except Exception as e:
        retro_content = f"# Retrospective\n\nFailed to generate: {e}"
    retro_md = _extract_code_block(retro_content, "markdown") or retro_content
    if retro_md:
        retro_path = run_dir / "RETRO.md"
        existing = retro_path.read_text() if retro_path.exists() else ""
        if existing.strip():
            combined = existing.rstrip() + "\n\n---\n\n" + retro_md.lstrip()
            retro_path.write_text(combined)
            print(f"Appended RETRO.md in {run_dir}")
        else:
            retro_path.write_text(retro_md)
            print(f"Saved RETRO.md to {run_dir}")

    short_name = _generate_short_name(description, result, call_fn)
    _save_short_name(run_dir, short_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI experiment: LLM suggests vLLM changes, deploy and benchmark")
    parser.add_argument("--sweep", "-s", help="Sweep name (use runs from results/sweep-NAME/)")
    parser.add_argument("--allow-model-change", action="store_true", help="Allow agent to try quantized model variants")
    parser.add_argument("--refresh-leaderboard", action="store_true", help="Just write leaderboard.txt to sweep dir and exit")
    args = parser.parse_args()
    allow_model_change = args.allow_model_change

    sweep = (args.sweep or os.environ.get("SWEEP", "")).strip()
    if sweep:
        sweep_dir = RESULTS_DIR / f"sweep-{sweep.lower().replace(' ', '-')}"
        if not sweep_dir.exists():
            print(f"Sweep '{sweep}' not found. Run 'make sweep SWEEP={sweep}' first.")
            return 1
        runs_dir = sweep_dir
        results_txt = sweep_dir / "results.txt"
    else:
        sweep_dir = None
        runs_dir = RUNS_DIR
        results_txt = RESULTS_DIR / "results.txt"

    if args.refresh_leaderboard:
        if not sweep_dir:
            print("--refresh-leaderboard requires --sweep")
            return 1
        _write_leaderboard_to_sweep(sweep_dir)
        print(f"Wrote {sweep_dir / 'leaderboard.txt'}")
        return 0

    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    model = os.environ.get("AI_MODEL", "")
    if provider == "anthropic":
        model = model or "claude-opus-4-6"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY"); return 1
        call_fn = lambda p: _call_anthropic(p, model)
    elif provider == "openai":
        model = model or "gpt-5-codex"
        if not os.environ.get("OPENAI_API_KEY"):
            print("Set OPENAI_API_KEY"); return 1
        call_fn = lambda p: _call_openai(p, model)
    else:
        print("AI_PROVIDER must be 'anthropic' or 'openai'"); return 1

    if not RUNLLM.exists():
        print("runllm submodule not found"); return 1

    # Determine which model subdir to use
    model_dir = DEFAULT_MODEL_DIR
    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            _sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            model_dir = _sm.get("model_dir", DEFAULT_MODEL_DIR)
        except Exception:
            pass
    runllm_model = RUNLLM / model_dir

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = (sweep_dir / ts) if sweep_dir else (RUNS_DIR / f"exp_{ts}")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Agent changes go only in run_dir/runllm. Base = best-runllm (sweep) or model subdir.
    experiment_dir = run_dir / "runllm"
    if experiment_dir.exists():
        shutil.rmtree(experiment_dir)
    base_runllm = runllm_model
    if sweep_dir:
        best_link = sweep_dir / "best-runllm"
        try:
            if best_link.exists():
                resolved = best_link.resolve() if best_link.is_symlink() else best_link
                if resolved.exists() and ((resolved / "vllm-config.yaml").exists() or (resolved / "vllm-qwen.yaml").exists()):
                    base_runllm = resolved
        except OSError:
            pass
        if base_runllm == runllm_model and (sweep_dir / "baseline" / "runllm").exists():
            base_runllm = sweep_dir / "baseline" / "runllm"
    shutil.copytree(base_runllm, experiment_dir, ignore=shutil.ignore_patterns(".git"))

    makefile_content = (base_runllm / "Makefile").read_text()
    _vllm_cfg = base_runllm / "vllm-config.yaml"
    if not _vllm_cfg.exists():
        _vllm_cfg = base_runllm / "vllm-qwen.yaml"  # legacy runs
    vllm_content = _vllm_cfg.read_text()
    # Ensure experiment_dir always uses the new name
    (experiment_dir / "vllm-config.yaml").write_text(vllm_content)
    runs_for_context = sweep_dir or RUNS_DIR
    leaderboard = _get_experiment_leaderboard(runs_for_context, PROJECT_ROOT)
    if sweep_dir:
        _write_leaderboard_to_sweep(sweep_dir)
    workload = _get_workload_description(runs_for_context)
    profile_context = _get_profile_context(runs_for_context, PROJECT_ROOT)

    # Include the most recent run retro alongside the synthesized summary.
    latest_retro_section = ""
    if sweep_dir:
        latest_run_name, latest_retro = _get_latest_retro(sweep_dir)
        if latest_retro:
            latest_retro_section = (
                f"\n## Most recent run retro ({latest_run_name})\n\n"
                f"{latest_retro[:4000]}\n"
            )

    # Generate FULL_RETRO.txt — LLM-synthesized summary of all run retros
    full_retro_section = ""
    if sweep_dir:
        print("Synthesizing retros from all runs into FULL_RETRO.txt...")
        full_retro = _generate_full_retro(sweep_dir, call_fn)
        if full_retro:
            (sweep_dir / "FULL_RETRO.txt").write_text(full_retro)
            full_retro_section = f"\n## Lessons learned from all previous runs\n\n{full_retro}\n"
    elif runs_for_context and runs_for_context.exists():
        raw = _collect_all_retros(runs_for_context)
        if raw:
            full_retro_section = f"\n## Lessons from previous runs\n\n{raw[:3000]}\n"

    # Read optional meta-feedback (human/external-model suggestions)
    meta_feedback_section = ""
    meta_feedback_file = (sweep_dir or runs_for_context) / "meta-feedback.txt"
    if meta_feedback_file.exists():
        try:
            fb = meta_feedback_file.read_text().strip()
            if fb:
                meta_feedback_section = f"\n## Meta-feedback (suggestions from an external reviewer — consider these for your next experiment)\n\n{fb}\n"
        except Exception:
            pass

    # Load vLLM tuning guide if available
    tuning_guide_section = ""
    tuning_guide_file = PROJECT_ROOT / "docs" / "vllm_tuning_guide.md"
    if tuning_guide_file.exists():
        try:
            tg = tuning_guide_file.read_text().strip()
            if tg:
                tuning_guide_section = f"\n## vLLM Tuning Guide (from official docs)\n\n{tg}\n"
        except Exception:
            pass

    # Read optimization goal from sweep metadata
    goal = "Minimize latency and maximize throughput (tok/s)."
    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            if sm.get("goal"):
                goal = sm["goal"]
        except Exception:
            pass

    model_change_section = ""
    if allow_model_change:
        model_change_section = """
## Model variants (ALLOW_MODEL_CHANGE=1 is set)

You MAY change the `--model` to a quantized variant of the same model family. This can significantly reduce memory usage and improve throughput/latency. Options:
- `Qwen/Qwen2.5-1.5B-Instruct` (current, FP16/BF16 baseline)
- `Qwen/Qwen2.5-1.5B-Instruct-AWQ` (4-bit AWQ, use `--dtype half --quantization awq`)
- `Qwen/Qwen2.5-1.5B-Instruct-GPTQ-Int4` (4-bit GPTQ, use `--quantization gptq`)
- `Qwen/Qwen2.5-1.5B-Instruct-GPTQ-Int8` (8-bit GPTQ, use `--quantization gptq`)
- `Qwen/Qwen2.5-0.5B-Instruct` (smaller model, much faster but lower quality)
- `Qwen/Qwen2.5-3B-Instruct` (larger model, higher quality but slower)

When changing the model, also update the Makefile's `VLLM_MODEL` variable to match, and return the Makefile in a ```makefile block```.
Do NOT change to a completely different model family—stay within Qwen2.5.
"""
    hardware_desc = _describe_hardware(vllm_content)

    prompt = f"""You are optimizing vLLM inference on Kubernetes (H200 GPU, CoreWeave).

**Hardware:** {hardware_desc}
**Benchmark workload:** {workload}
**Goal:** {goal}

## Current best config (your baseline to improve on)

```yaml
{vllm_content}
```

## Experiment leaderboard

{leaderboard}
{profile_context}{latest_retro_section}{full_retro_section}{meta_feedback_section}
## Hard constraints (DO NOT violate)

- Keep `apiVersion: v1, kind: Pod`. Do NOT change `metadata.name`, `restartPolicy`, or image (`vllm/vllm-openai:nightly`).
- Do NOT use Deployments/ReplicaSets, probes, `--host`, or `--port`.
- PRESERVE the entire `command:`/`args:` init script, `volumeMounts:`, and `volumes:` EXACTLY as-is. The init script installs tensorizer, patches vllm bugs, then runs `exec vllm serve`. You may ONLY modify the `vllm serve` flags on the continued command lines after `exec vllm serve`.
- Do NOT change `--load-format`, `--model-loader-extra-config`, `--served-model-name`, or the model path (required for tensorizer PVC loading).
- `--disable-log-requests` and `--num-scheduler-steps` do NOT exist in this image.
- Do NOT use `--disable-log-stats`. Logs and metrics are needed for diagnosis — disabling them is not a valid optimization.
{"- Do NOT change the --model (model changes not enabled for this sweep)" if not allow_model_change else ""}
{model_change_section}
## Observed quirks

- Diagnose from evidence (leaderboard, logs), not assumptions. Many successful `POST /v1/chat/completions` in logs = benchmark progress, likely a harness/watchdog issue not a config failure.
- `VLLM_ATTENTION_BACKEND` env var warns "Unknown vLLM environment variable". Do NOT introduce it if absent; only change it as a dedicated experiment if already present.
- `--performance-mode` has failed before. Do NOT introduce unless already in a successful leaderboard run.
- `draft_model` speculative decoding is broken on this vLLM nightly with our tensorized main model. Do NOT propose draft-model speculation, even with `draft_load_config.load_format=auto`.
- If you try speculative decoding, use ngram only and use dot-notation CLI args (`--speculative-config.method ngram`, etc.), not JSON blob syntax.

## vLLM serve flags reference (performance-relevant subset)

**Model & precision:** `--dtype` (auto|half|bfloat16), `--quantization` (awq|gptq|fp8|None), `--max-model-len` (context length, -1=auto), `--enforce-eager` (disable CUDA graphs; can reduce TTFT, may hurt throughput)

**GPU & memory:** `--tensor-parallel-size` (-tp), `--gpu-memory-utilization` (0-1, default 0.9), `--kv-cache-dtype` (auto|fp8|fp8_e4m3|bfloat16 — fp8 halves KV cache memory), `--block-size` (KV cache block size)

**Scheduling & batching:** `--max-num-batched-tokens`, `--max-num-seqs`, `--enable-chunked-prefill`, `--max-num-partial-prefills` (default 1), `--async-scheduling`

**Caching:** `--enable-prefix-caching` (cache common prefix KV blocks)

**Speculative decoding:** prefer ngram only on this image, using dot-notation CLI args such as `--speculative-config.method ngram`, `--speculative-config.num_speculative_tokens 5`, `--speculative-config.prompt_lookup_max 5`. Do NOT use draft-model speculative decoding here.

**Compilation & CUDA graphs:** `--compilation-config '{{"mode": N}}'` (0=none, 1=inductor, 2=reduce-overhead, 3=max-autotune). `--performance-mode` balanced|interactivity|throughput.

**Env vars** (add to `spec.containers[0].env`): `VLLM_ATTENTION_BACKEND` (FLASH_ATTN|FLASHINFER), `VLLM_USE_TRITON_FLASH_ATTN`, `VLLM_WORKER_MULTIPROC_METHOD` (spawn|fork), `VLLM_LOGGING_LEVEL` (WARNING to reduce overhead).

**Other:** `--optimization-level` (0-3, default 2), `--attention-backend` (CLI alternative to env var), `--disable-log-stats`.

{tuning_guide_section}
## Your task

Pick ONE untried change (check leaderboard) backed by evidence. Change exactly one knob.
This run should test exactly one experiment hypothesis. If that hypothesis benchmarks successfully, stop even if it regresses.
1. State: `knob: old -> new` and why (2-3 sentences)
2. write_file('vllm-config.yaml', <complete YAML>)
{"3. If you changed the model, also write_file('Makefile', ...) with updated VLLM_MODEL." if allow_model_change else ""}
3. Optionally run_benchmark(<description>) to deploy and test."""

    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            benchmark = sm.get("benchmark", "quick")
        except Exception:
            benchmark = "quick"
    else:
        benchmark = os.environ.get("BENCHMARK", "").lower()
        if not benchmark or benchmark not in BENCHMARK_PRESETS:
            benchmark = "quick"
    if benchmark not in BENCHMARK_PRESETS:
        benchmark = "quick"

    # Keep retries for debugging benchmark crashes/bugs only; next runs should try new experiments.
    max_attempts = 3
    failure_context: dict | None = None
    last_description = ""

    for attempt in range(max_attempts):
        if attempt > 0 and failure_context:
            result_msg = failure_context.get("result", "")
            if _is_infrastructure_error(result_msg):
                print("\n*** Infrastructure error (not fixable by vLLM config) ***")
                print(result_msg[:600])
                print("\nThis is a Kubernetes/kubectl setup issue. Check:")
                print("  1. KUBECONFIG is set and points to your cluster")
                print("  2. kubectl auth can-i delete pods  (must return yes)")
                print("  3. kubectl get pods  (should reach the cluster)")
                return 1

            vllm_cur = (experiment_dir / "vllm-config.yaml").read_text()
            user_prompt = f"""Attempt {attempt} FAILED: {result_msg}

The run directory is '{run_dir.name}'. Use tools to investigate:
- read_logs('{run_dir.name}', 'deploy') for deploy.log
- read_logs('{run_dir.name}', 'kubectl') for kubectl logs
- kubectl_get('pods') to check pod status

**Failed vllm-config.yaml:**
```yaml
{vllm_cur[:2500]}
```

**Fix rules:**
- Diagnose using the tools, not assumptions. Check logs before changing config.
- This is NOT a fresh optimization pass. Do NOT pick a new experiment or a different tuning idea.
- Only repair the same experiment so it can be measured once, or conclude it should stop here.
- If the evidence shows a harness/watchdog issue (not a config problem), say NO_CONFIG_CHANGE: <reason>.
- Otherwise fix minimally: repair the failed experiment only, reverting the last change first if needed.
- Keep Pod kind. Image: vllm/vllm-openai:nightly.
- PRESERVE the `command:` / `args:` init script, PVC volumeMounts/volumes, and tensorizer flags exactly as-is. Only modify vllm serve flags.
- No `--disable-log-requests` (doesn't exist). No `--disable-log-stats` (logs/metrics needed for diagnosis). No `VLLM_ATTENTION_BACKEND` if absent.

When ready, call write_file('vllm-config.yaml', <complete fixed YAML>)."""
            print(f"Retry {attempt + 1}/{max_attempts}: agent investigating failure with tools...")
        else:
            user_prompt = prompt

        _write_progress("llm_call", {"experiment_dir": str(experiment_dir), "attempt": attempt + 1})
        print(f"Calling {provider} ({model})..." + (f" (attempt {attempt + 1}/{max_attempts})" if attempt > 0 else ""))

        # Set up tool context
        tool_env = os.environ.copy()
        tool_env["KUBECONFIG"] = os.environ.get("KUBECONFIG", "")
        ctx = ToolContext(
            project_root=PROJECT_ROOT,
            experiment_dir=experiment_dir,
            run_dir=run_dir,
            sweep_dir=sweep_dir,
            sweep=sweep or None,
            benchmark=benchmark,
            ts=ts,
            env=tool_env,
            deploy_and_benchmark=_deploy_and_benchmark,
            log_path=run_dir / "agent.log",
        )

        try:
            agent_result = run_agent(TOOL_SYSTEM_PROMPT, user_prompt, provider, model, ctx, max_turns=AGENT_MAX_TURNS)
        except Exception as e:
            print(f"Agent error: {e}")
            _append_result(experiment_dir, f"Agent error: {e}", "", results_path=results_txt)
            return 1

        _write_agent_result_log(run_dir, agent_result, sweep_dir)

        if agent_result.error:
            print(f"Agent loop error: {agent_result.error}")
            _append_result(experiment_dir, agent_result.error, "", results_path=results_txt)
            return 1

        # Determine config content: prefer tool-written config, fall back to YAML extraction
        yaml_content = None
        no_config_change_reason = None

        if agent_result.config_written:
            yaml_content = agent_result.config_content
            description = agent_result.description or _extract_description(agent_result.text)
        else:
            no_config_change_reason = _extract_no_config_change_reason(agent_result.text)
            yaml_content = _extract_yaml(agent_result.text)
            if no_config_change_reason and not yaml_content:
                if attempt > 0:
                    stop_msg = f"Stopping retries: {no_config_change_reason}"
                    print(stop_msg)
                    _append_result(
                        experiment_dir,
                        stop_msg,
                        (failure_context or {}).get("result", ""),
                        success=False,
                        run_dir=run_dir,
                        results_path=results_txt,
                    )
                    return 1
                yaml_content = (experiment_dir / "vllm-config.yaml").read_text()
                description = f"No config change: {no_config_change_reason}"
            elif yaml_content:
                description = agent_result.description or _extract_description(agent_result.text)
            else:
                description = _extract_description(agent_result.text)
                err = "Could not extract YAML from agent response"
                print(err)
                _append_result(experiment_dir, description, err, results_path=results_txt)
                return 1

        # Validate: revert unauthorized model changes
        if not allow_model_change and yaml_content:
            baseline_model_m = re.search(r'"--model"\s*\n\s*-\s*"([^"]+)"', vllm_content)
            proposed_model_m = re.search(r'"--model"\s*\n\s*-\s*"([^"]+)"', yaml_content)
            if baseline_model_m and proposed_model_m:
                baseline_model = baseline_model_m.group(1)
                proposed_model = proposed_model_m.group(1)
                if proposed_model != baseline_model:
                    print(f"Agent tried to change model to {proposed_model} — reverting to {baseline_model}")
                    yaml_content = yaml_content.replace(proposed_model, baseline_model)

        last_description = description

        if not agent_result.config_written:
            (experiment_dir / "vllm-config.yaml").write_text(yaml_content)
            shutil.copy(experiment_dir / "vllm-config.yaml", run_dir / "vllm_config.yaml")
            makefile_new = _extract_makefile(agent_result.text) or (experiment_dir / "Makefile").read_text()
            (experiment_dir / "Makefile").write_text(makefile_new)

        (run_dir / "run_metadata.json").write_text(json.dumps({
            "timestamp": ts,
            "description": description[:500],
            "experiment_dir": str(experiment_dir),
            "benchmark": benchmark,
            "sweep": sweep or None,
            "attempt": attempt + 1,
            "tools_used": len(agent_result.tool_log),
        }, indent=2))

        print(f"Run dir: {run_dir} (modified runllm in run_dir/runllm/)")
        print()
        print("━" * 60)
        print("AGENT IMPROVEMENT STRATEGY")
        print("━" * 60)
        print()
        print(description)
        print()
        print(f"Attempt {attempt + 1}/{max_attempts}  |  Benchmark: {benchmark}" + (" (from sweep)" if sweep_dir else ""))
        if agent_result.tool_log:
            print(f"Tools used: {len(agent_result.tool_log)} calls")
        print("━" * 60)
        print()

        # If agent already ran benchmark via tool, use those results
        if agent_result.benchmark_ran:
            success = agent_result.benchmark_success
            result = agent_result.benchmark_result
        else:
            print("Deploying and running benchmark...")
            success, result = _deploy_and_benchmark(experiment_dir, benchmark, run_dir, ts, sweep=sweep or None)

        _append_result(experiment_dir, description, result, success=success, run_dir=run_dir, results_path=results_txt)

        # Write a short retro for every run (success or failure)
        _write_run_retro(
            run_dir=run_dir, experiment_dir=experiment_dir, description=description,
            result=result, success=success, attempt=attempt + 1, max_attempts=max_attempts,
            provider=provider, model=model, sweep_dir=sweep_dir, sweep=sweep,
            benchmark=benchmark, ts=ts, call_fn=call_fn,
        )

        if success:
            if sweep_dir:
                from sweep_utils import update_best_runllm
                update_best_runllm(sweep_dir, runllm_model)
                _write_leaderboard_to_sweep(sweep_dir)
            print(f"Results: {result}")
            return 0

        # Gather failure context for retry
        failure_context = {"result": result}
        print(f"Attempt {attempt + 1} failed: {result[:200]}...")

    # Exhausted retries
    _append_result(experiment_dir, last_description, f"Failed after {max_attempts} attempts. Last error: {(failure_context or {}).get('result', '')}", success=False, run_dir=run_dir, results_path=results_txt)
    if sweep_dir:
        if (run_dir / "run_metadata.json").exists():
            try:
                rm = json.loads((run_dir / "run_metadata.json").read_text())
                rm["result"] = (failure_context or {}).get("result", "")[:500]
                (run_dir / "run_metadata.json").write_text(json.dumps(rm, indent=2))
            except Exception:
                pass
        _write_leaderboard_to_sweep(sweep_dir)
    print(f"Results: Failed after {max_attempts} attempts. See {run_dir}/RETRO.md")
    return 1


def _write_conversation(run_dir: Path, turns: list[tuple[str, str]], sweep_dir: Path | None = None) -> None:
    """Save full agent conversation to run_dir/agent.log. If sweep_dir, also append to sweep_dir/agent.log."""
    lines = []
    for i, (prompt, response) in enumerate(turns, 1):
        lines.append(f"\n{'='*60}\nTURN {i} - USER (prompt)\n{'='*60}\n\n{prompt}")
        lines.append(f"\n{'='*60}\nTURN {i} - ASSISTANT (response)\n{'='*60}\n\n{response}")
    content = "\n".join(lines).lstrip() if lines else "(no conversation)"
    (run_dir / "agent.log").write_text(content, encoding="utf-8")
    if sweep_dir:
        sweep_log = sweep_dir / "agent.log"
        header = f"\n\n{'#'*70}\n# Run {run_dir.name} ({datetime.now().isoformat()})\n{'#'*70}\n"
        with open(sweep_log, "a", encoding="utf-8") as f:
            f.write(header)
            f.write(content)


def _write_agent_result_log(run_dir: Path, agent_result: AgentResult, sweep_dir: Path | None = None) -> None:
    """Append tool summary to the live agent.log and copy to sweep log."""
    log_file = run_dir / "agent.log"

    summary_lines = []
    if agent_result.tool_log:
        summary_lines.append(f"\n{'='*60}\nTOOL CALL SUMMARY\n{'='*60}\n")
        for tl in agent_result.tool_log:
            summary_lines.append(f"  {tl['tool']}({json.dumps(tl.get('arguments', {}), default=str)}) -> {tl['result_length']} chars ({tl['elapsed_s']}s)")
        (run_dir / "tool_log.json").write_text(json.dumps(agent_result.tool_log, indent=2))

    if summary_lines:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n".join(summary_lines))
                f.write("\n")
        except Exception:
            pass

    if sweep_dir:
        sweep_log = sweep_dir / "agent.log"
        header = f"\n\n{'#'*70}\n# Run {run_dir.name} ({datetime.now().isoformat()}) [tool-calling]\n{'#'*70}\n"
        try:
            run_log_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
            with open(sweep_log, "a", encoding="utf-8") as f:
                f.write(header)
                f.write(run_log_content)
        except Exception:
            pass


def _append_result(experiment_dir: Path, description: str, result: str, success: bool = True, run_dir: Path | None = None, results_path: Path | None = None) -> None:
    path = results_path or (RESULTS_DIR / "results.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 60 + "\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Experiment directory: {experiment_dir}\n")
        if run_dir:
            f.write(f"Run directory (logs): {run_dir}\n")
        f.write(f"Summary: {description[:500]}\n")
        f.write(f"Success: {success}\n")
        f.write(f"Results: {result}\n")
        f.write("=" * 60 + "\n")


def backfill_short_names():
    """Generate short names for all existing runs that don't have one."""
    provider = os.environ.get("AI_PROVIDER", "openai")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    call_fn = (lambda p: _call_openai(p, model)) if "openai" in provider else (lambda p: _call_anthropic(p, model))

    count = 0
    for sweep_dir in sorted(RESULTS_DIR.iterdir()):
        if not sweep_dir.is_dir() or not sweep_dir.name.startswith("sweep-"):
            continue
        for run_dir in sorted(sweep_dir.iterdir()):
            if not run_dir.is_dir() or run_dir.name.startswith(".") or run_dir.name == "best-runllm":
                continue
            if _read_short_name(run_dir):
                continue
            meta = {}
            mf = run_dir / "run_metadata.json"
            if mf.exists():
                try:
                    meta = json.loads(mf.read_text())
                except Exception:
                    pass
            desc = meta.get("description", run_dir.name)
            result = meta.get("result", "")
            name = _generate_short_name(desc, result, call_fn)
            if name:
                _save_short_name(run_dir, name)
                count += 1
                print(f"  {run_dir.name} -> {name}")
    print(f"Backfilled {count} short names.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backfill-names":
        backfill_short_names()
    else:
        sys.exit(main())
