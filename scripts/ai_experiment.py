#!/usr/bin/env python3
"""
AI experiment: show agent (Opus/Codex) runllm code + benchmark data, get suggested changes,
write modified runllm to results/runs or results/sweep-NAME/ only (never project root), deploy, benchmark.

Usage:
  AI_PROVIDER=anthropic AI_MODEL=claude-opus-4-6 make experiment
  AI_PROVIDER=openai AI_MODEL=gpt-5.4 make experiment
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
from k8s_benchmark import run_benchmark_k8s
from model_variants import backend_from_model_dir, infer_backend, infer_backend_from_runllm_dir, list_model_variants
from sweep_state import (
    SWEEP_STOP_EXIT_CODE,
    classify_failure_text,
    effective_agent_model,
    should_stop_sweep,
    write_sweep_overview,
)
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

# If no log activity for this many seconds during deploy/health phases, abort.
INSPECT_AFTER_SEC = int(os.environ.get("EXPERIMENT_INSPECT_AFTER_SEC", "180"))

# Hard ceiling for deploy+health phases regardless of log activity.
DEPLOY_HARD_TIMEOUT = int(os.environ.get("EXPERIMENT_DEPLOY_HARD_TIMEOUT", "600"))

# If query count unchanged for this many seconds during benchmark, assume stuck and abort.
# 60s default gives non-synchronous profiles (concurrent, sweep) enough time between progress updates.
QUERY_STALE_SEC = int(os.environ.get("EXPERIMENT_QUERY_STALE_SEC", "60"))

# Timeout for sample query before benchmark (must complete or we abort)
SAMPLE_QUERY_TIMEOUT = int(os.environ.get("EXPERIMENT_SAMPLE_QUERY_TIMEOUT", "30"))

AGENT_MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "50"))
PROMPT_LEADERBOARD_SUCCESS_LIMIT = int(os.environ.get("PROMPT_LEADERBOARD_SUCCESS_LIMIT", "8"))
PROMPT_LEADERBOARD_FAILURE_LIMIT = int(os.environ.get("PROMPT_LEADERBOARD_FAILURE_LIMIT", "8"))
FULL_RETRO_REFRESH_EVERY = int(os.environ.get("FULL_RETRO_REFRESH_EVERY", "5"))
RESEARCH_MEMORY_REFRESH_EVERY = int(os.environ.get("RESEARCH_MEMORY_REFRESH_EVERY", "3"))
PROMPT_RESEARCH_MEMORY_CHAR_LIMIT = int(os.environ.get("PROMPT_RESEARCH_MEMORY_CHAR_LIMIT", "2200"))

TOOL_SYSTEM_PROMPT = """\
You are an LLM serving optimizer agent on Kubernetes (H200 GPU, CoreWeave).
Pick ONE simple change most likely to improve performance, then test it.

## Workflow
1. Read the leaderboard and lessons learned (in the prompt).
2. Pick one untried change. Do NOT bundle multiple changes.
3. Read the sweep research memory in the prompt first. Use read_file/read_logs to inspect past runs. Use search_web/fetch_url only if that local memory does not already answer the question.
4. Write the config: write_file('vllm-config.yaml', <complete pod YAML>).
5. Optionally: run_benchmark(<description>) to deploy and test.

## Run policy
- One run = one experiment. After you benchmark a config, stop. Do NOT pivot to a second experiment in the same run.
- If the benchmark exposes a crash, invalid arg, startup bug, or harness/runtime issue, you may debug that SAME config idea.
- Do NOT turn a retry into a fresh optimization pass. Let the next run/agent try the next experiment.
- Prefer local evidence over web search. Assume repeated failures and prior research are already documented unless the prompt/logs show a genuinely new issue.

## File safety
- write_file writes ONLY to the isolated per-run directory. You can only write 'vllm-config.yaml' and 'Makefile'.
- read_file can read from results/, runllm/, docs/, scripts/.

## Rules — DO NOT violate
- Do NOT change the model unless ALLOW_MODEL_CHANGE=1. Switching models is cheating, not optimizing.
- If the prompt offers multiple backend variants, you MAY switch backend, but treat the backend switch itself as the single experiment for that run.
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


def _research_cache_paths(sweep_dir: Path) -> tuple[Path, Path, Path]:
    return (
        sweep_dir / "RESEARCH_LOG.md",
        sweep_dir / "RESEARCH_MEMORY.md",
        sweep_dir / "RESEARCH_MEMORY.meta.json",
    )


def _collect_research_log(sweep_dir: Path | None) -> str:
    if not sweep_dir or not sweep_dir.exists():
        return ""
    log_path, _, _ = _research_cache_paths(sweep_dir)
    if not log_path.exists():
        return ""
    try:
        return log_path.read_text().strip()
    except Exception:
        return ""


def _research_entry_count(raw_log: str) -> int:
    return len(re.findall(r"^##\s", raw_log, flags=re.MULTILINE))


def _generate_research_memory(sweep_dir: Path, call_fn) -> str:
    raw_log = _collect_research_log(sweep_dir)
    if not raw_log:
        return ""

    prompt = f"""Below is a sweep-local log of external research already done by previous agents.
Synthesize it into a compact memory document that future agents should read before doing more web research.

Rules:
- Deduplicate aggressively.
- Distinguish confirmed findings from tentative ones.
- Organize into: Confirmed findings, likely dead ends / avoid repeating, open questions, useful sources.
- Keep only actionable research that changes tuning/debugging decisions.
- Mention backend/workload specificity when relevant.
- Be terse. No filler. Target 15-30 lines.

Raw research log:
{raw_log}"""
    try:
        return call_fn(prompt).strip()
    except Exception as e:
        return f"(Failed to synthesize research memory: {e})\n\n{raw_log[:3000]}"


def _should_refresh_research_memory(sweep_dir: Path) -> bool:
    log_path, memory_path, meta_path = _research_cache_paths(sweep_dir)
    if not log_path.exists():
        return False
    if not memory_path.exists() or not meta_path.exists():
        return True
    meta = _read_json_file(meta_path)
    raw_log = _collect_research_log(sweep_dir)
    entry_count = _research_entry_count(raw_log)
    source_chars = len(raw_log)
    previous_entries = int(meta.get("entry_count", -1) or -1)
    previous_chars = int(meta.get("source_chars", -1) or -1)
    if previous_entries < 0 or previous_chars < 0:
        return True
    if entry_count != previous_entries and entry_count - previous_entries >= RESEARCH_MEMORY_REFRESH_EVERY:
        return True
    if source_chars != previous_chars and previous_entries == entry_count:
        return True
    return False


def _get_or_refresh_research_memory(sweep_dir: Path, call_fn) -> str:
    log_path, memory_path, meta_path = _research_cache_paths(sweep_dir)
    if not log_path.exists():
        return ""
    if not _should_refresh_research_memory(sweep_dir) and memory_path.exists():
        try:
            return memory_path.read_text().strip()
        except Exception:
            pass
    memory = _generate_research_memory(sweep_dir, call_fn).strip()
    if not memory:
        return ""
    raw_log = _collect_research_log(sweep_dir)
    meta = {
        "entry_count": _research_entry_count(raw_log),
        "source_chars": len(raw_log),
        "updated_at": datetime.now().isoformat(),
    }
    memory_path.write_text(memory)
    meta_path.write_text(json.dumps(meta, indent=2))
    return memory


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _get_run_dirs(runs_base: Path | None) -> list[Path]:
    if not runs_base or not runs_base.exists():
        return []
    return sorted(
        [d for d in runs_base.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.name,
        reverse=True,
    )


def _best_run_name_for_objective(runs_base: Path | None) -> str:
    if not runs_base or not runs_base.exists():
        return ""
    sweep_name = runs_base.name.replace("sweep-", "")
    objective = sweep_objective(sweep_name)
    best_name = ""
    best_key: tuple[float, float] | tuple[float] | None = None
    for d in _get_run_dirs(runs_base):
        benchmarks = d / "benchmarks.json"
        if not benchmarks.exists():
            continue
        try:
            data = json.loads(benchmarks.read_text())
            if not is_valid_run(d, data):
                continue
            metrics = data.get("benchmarks", [{}])[0].get("metrics", {})
            latency = metric_mean(metrics, "request_latency")
            throughput = metric_mean(metrics, "tokens_per_second")
            ttft = metric_mean(metrics, "time_to_first_token_ms")
            if objective == "throughput":
                key = (-(throughput or 0), latency or 999999)
            elif objective == "ttft":
                key = (ttft or 999999,)
            else:
                key = (latency or 999999,)
            if best_key is None or key < best_key:
                best_key = key
                best_name = d.name
        except Exception:
            continue
    return best_name


def _full_retro_cache_paths(sweep_dir: Path) -> tuple[Path, Path]:
    return sweep_dir / "FULL_RETRO.txt", sweep_dir / "FULL_RETRO.meta.json"


def _failure_category_signature(runs_base: Path | None) -> list[str]:
    categories: set[str] = set()
    for d in _get_run_dirs(runs_base):
        meta_path = d / "run_metadata.json"
        if not meta_path.exists():
            continue
        meta = _read_json_file(meta_path)
        if meta.get("success"):
            continue
        category = str(((meta.get("failure_classification") or {}).get("category")) or "").strip()
        if category:
            categories.add(category)
    return sorted(categories)


def _should_refresh_full_retro(sweep_dir: Path) -> bool:
    retro_path, meta_path = _full_retro_cache_paths(sweep_dir)
    if not retro_path.exists() or not meta_path.exists():
        return True
    meta = _read_json_file(meta_path)
    retro_runs = [d.name for d in _get_run_dirs(sweep_dir) if (d / "RETRO.md").exists()]
    run_count = len(retro_runs)
    latest_run = retro_runs[0] if retro_runs else ""
    best_run = _best_run_name_for_objective(sweep_dir)
    previous_count = int(meta.get("source_run_count", -1) or -1)
    failure_categories = _failure_category_signature(sweep_dir)
    if run_count <= 0:
        return False
    if best_run and best_run != meta.get("best_run"):
        return True
    if failure_categories != meta.get("failure_categories", []):
        return True
    if previous_count < 0:
        return True
    if run_count - previous_count >= FULL_RETRO_REFRESH_EVERY:
        return True
    if not meta.get("latest_run"):
        return True
    if latest_run and previous_count == 0:
        return True
    return False


def _get_or_refresh_full_retro(sweep_dir: Path, call_fn) -> str:
    retro_path, meta_path = _full_retro_cache_paths(sweep_dir)
    if not _should_refresh_full_retro(sweep_dir) and retro_path.exists():
        try:
            return retro_path.read_text().strip()
        except Exception:
            pass
    full_retro = _generate_full_retro(sweep_dir, call_fn).strip()
    if not full_retro:
        return ""
    retro_runs = [d.name for d in _get_run_dirs(sweep_dir) if (d / "RETRO.md").exists()]
    meta = {
        "source_run_count": len(retro_runs),
        "latest_run": retro_runs[0] if retro_runs else "",
        "best_run": _best_run_name_for_objective(sweep_dir),
        "failure_categories": _failure_category_signature(sweep_dir),
        "updated_at": datetime.now().isoformat(),
    }
    retro_path.write_text(full_retro)
    meta_path.write_text(json.dumps(meta, indent=2))
    return full_retro


def _result_from_metadata(run_dir: Path) -> str:
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        return ""
    return str(_read_json_file(metadata_path).get("result", "")).strip()


def _known_issue_summary_line(category: str, count: int, example: str) -> str:
    label = category.replace("_", " ")
    line = f"- `{label}` seen {count} time(s)"
    if example:
        line += f": {example[:180]}"
    return line


def _build_known_issues_section(runs_base: Path | None) -> str:
    if not runs_base or not runs_base.exists():
        return ""
    category_counts: dict[str, int] = {}
    category_examples: dict[str, str] = {}
    harness_lines: dict[str, int] = {}
    good_lines: list[str] = []
    for d in _get_run_dirs(runs_base):
        meta = _read_json_file(d / "run_metadata.json") if (d / "run_metadata.json").exists() else {}
        short_name = _read_short_name(d) or meta.get("description", "") or d.name
        if meta.get("success") and (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                if not is_valid_run(d, data):
                    continue
                metrics = data.get("benchmarks", [{}])[0].get("metrics", {})
                summary = _fmt_summary(metrics)
                if summary and summary != "—":
                    good_lines.append(f"- `{short_name[:70]}`: {summary}")
            except Exception:
                pass
            continue

        classification = meta.get("failure_classification") or {}
        category = str(classification.get("category") or "unknown").strip().lower() or "unknown"
        summary = str(classification.get("summary") or meta.get("result") or "").strip()
        category_counts[category] = category_counts.get(category, 0) + 1
        if summary and category not in category_examples:
            category_examples[category] = summary

        result = str(meta.get("result") or "").lower()
        if "sample query returned empty or invalid response" in result:
            harness_lines["sample query invalid; likely harness/parser mismatch"] = harness_lines.get(
                "sample query invalid; likely harness/parser mismatch", 0
            ) + 1
        if "stuck in phase 'pod_wait'" in result or "stuck in phase 'health_check'" in result:
            harness_lines["watchdog timeout during pod wait/health check"] = harness_lines.get(
                "watchdog timeout during pod wait/health check", 0
            ) + 1

    lines = ["## Structured sweep memory", ""]
    if good_lines:
        lines.append("Best known frontier:")
        lines.extend(good_lines[:4])
        lines.append("")
    if category_counts:
        lines.append("Known bad / repeated failure classes:")
        ranked = sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for category, count in ranked[:6]:
            lines.append(_known_issue_summary_line(category, count, category_examples.get(category, "")))
        lines.append("")
    if harness_lines:
        lines.append("Known harness-only patterns (do not spend a fresh tuning run rediscovering these):")
        for label, count in sorted(harness_lines.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {label} ({count}x)")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_agent_context_cache(sweep_dir: Path) -> None:
    if not sweep_dir or not sweep_dir.exists():
        return
    context_path = sweep_dir / "AGENT_CONTEXT.md"
    _, research_memory_path, _ = _research_cache_paths(sweep_dir)
    leaderboard = _get_experiment_leaderboard(
        sweep_dir,
        PROJECT_ROOT,
        max_successes=PROMPT_LEADERBOARD_SUCCESS_LIMIT,
        max_failures=PROMPT_LEADERBOARD_FAILURE_LIMIT,
        compact=True,
    )
    known_issues = _build_known_issues_section(sweep_dir)
    pieces = ["# Compact agent context", "", leaderboard]
    if known_issues:
        pieces.extend(["", known_issues.rstrip()])
    if research_memory_path.exists():
        try:
            research_memory = research_memory_path.read_text().strip()
            if research_memory:
                pieces.extend([
                    "",
                    "## Sweep research memory",
                    "",
                    research_memory[:PROMPT_RESEARCH_MEMORY_CHAR_LIMIT],
                ])
        except Exception:
            pass
    context_path.write_text("\n".join(piece for piece in pieces if piece).strip() + "\n")


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


def _extract_model_identity(config_text: str) -> str | None:
    patterns = [
        r'--served-model-name\s+([^\s\\]+)',
        r'--model-path\s+([^\s\\]+)',
        r'"--model"\s*\n\s*-\s*"([^"]+)"',
        r'--model["\']?\s*\n\s*-\s*["\']?([^"\'\n\r]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, config_text)
        if match:
            return match.group(1).strip().rstrip("'\"")
    return None


def _load_backend_templates(runllm_root: Path, model_variants: list[str]) -> list[dict[str, str]]:
    templates: list[dict[str, str]] = []
    for model_dir in model_variants:
        variant_dir = runllm_root / model_dir
        cfg_path = variant_dir / "vllm-config.yaml"
        makefile_path = variant_dir / "Makefile"
        if not cfg_path.exists() or not makefile_path.exists():
            continue
        config_text = cfg_path.read_text()
        makefile_text = makefile_path.read_text()
        templates.append({
            "model_dir": model_dir,
            "backend": backend_from_model_dir(model_dir),
            "config_path": str(cfg_path.relative_to(runllm_root.parent)),
            "makefile_path": str(makefile_path.relative_to(runllm_root.parent)),
            "config_text": config_text,
            "makefile_text": makefile_text,
            "summary": _describe_hardware(config_text),
        })
    return templates


def _render_backend_templates_section(templates: list[dict[str, str]]) -> str:
    if len(templates) <= 1:
        return ""
    lines = [
        "## Backend variants available for this sweep",
        "",
        "You may keep the current backend or switch to one of these canonical variants.",
        "A backend switch counts as the ONE experiment change for the run, so do not bundle extra tuning with the switch.",
        "If you switch backend, replace BOTH `vllm-config.yaml` and `Makefile` from the chosen variant template before benchmarking.",
        "",
    ]
    for template in templates:
        lines.append(
            f"- `{template['backend']}` via `runllm/{template['model_dir']}` "
            f"({template['summary']}; config: `{template['config_path']}`, Makefile: `{template['makefile_path']}`)"
        )
    return "\n".join(lines) + "\n"


def _backend_label_for_run(run_dir: Path, meta: dict | None = None) -> str:
    if meta and meta.get("backend"):
        return str(meta["backend"])
    config_text = ""
    for cfg in ("vllm_config.yaml", "runllm/vllm-config.yaml", "runllm/vllm-qwen.yaml"):
        fp = run_dir / cfg
        if fp.exists():
            config_text = fp.read_text()
            break
    makefile_text = ""
    makefile_fp = run_dir / "runllm" / "Makefile"
    if makefile_fp.exists():
        makefile_text = makefile_fp.read_text()
    return infer_backend(config_text, makefile_text)


def _get_experiment_leaderboard(
    runs_base: Path,
    project_root: Path,
    *,
    max_successes: int | None = None,
    max_failures: int = 20,
    compact: bool = False,
) -> str:
    """Leaderboard ranked according to the sweep objective."""
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
        backend = _backend_label_for_run(d, meta)
        short_name = _read_short_name(d)
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                if not is_valid_run(d, data):
                    n_completed = completed_request_count(data)
                    failures.append({
                        "name": d.name,
                        "short_name": short_name,
                        "backend": backend,
                        "desc": desc,
                        "retro": _read_retro_summary(d),
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
                                      "backend": backend,
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
        retro = _read_retro_summary(d)
        if desc or result or retro:
            failures.append({
                "name": d.name,
                "short_name": short_name,
                "backend": backend,
                "desc": desc,
                "retro": retro,
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
        shown_successes = successes[:max_successes] if max_successes is not None else successes
        for s in shown_successes:
            header = s["name"]
            if s.get("short_name"):
                header += f"  [{s['short_name']}]"
            header += f"  <{s['backend']}>"
            lines.append(f"{header}  {s['metrics']}")
            if not compact and s.get("changes"):
                lines.append("  changes: " + "; ".join(s["changes"][:4]))
            lines.append("")
        if compact and len(successes) > len(shown_successes):
            lines.append(f"... {len(successes) - len(shown_successes)} more successful runs omitted")
            lines.append("")

    if failures:
        lines.append(f"\nFailed runs ({len(failures)} total — DO NOT repeat these strategies):")
        shown_failures = failures[:max_failures]
        for f in shown_failures:
            label = f['name']
            if f.get('short_name'):
                label += f"  [{f['short_name']}]"
            label += f"  <{f['backend']}>"
            summary = f.get('retro') or f.get('changes') or f['desc'][:120] or "no details"
            lines.append(f"  {label}: {summary}")
        if compact and len(failures) > len(shown_failures):
            lines.append(f"  ... {len(failures) - len(shown_failures)} more failed runs omitted")

    lines.append(f"\nTo get details on any run, use: read_file('results/{runs_base.name}/<run>/RETRO.md') or read_logs('<run>', 'benchmark')")

    return "\n".join(lines) if lines else "No experiments yet."


def _write_leaderboard_to_sweep(sweep_dir: Path) -> None:
    """Write the current leaderboard to sweep_dir/leaderboard.txt for easy viewing."""
    if not sweep_dir or not sweep_dir.exists():
        return
    leaderboard = _get_experiment_leaderboard(sweep_dir, PROJECT_ROOT)
    (sweep_dir / "leaderboard.txt").write_text(leaderboard)


def _update_sweep_metadata_agent(sweep_dir: Path | None, provider: str, model: str) -> None:
    if not sweep_dir:
        return
    metadata_path = sweep_dir / "sweep_metadata.json"
    if not metadata_path.exists():
        return
    try:
        metadata = json.loads(metadata_path.read_text())
    except Exception:
        return
    metadata["last_agent_provider"] = provider
    metadata["last_agent_model"] = model
    metadata_path.write_text(json.dumps(metadata, indent=2))


def _update_run_metadata(run_dir: Path, **updates: Any) -> dict[str, Any]:
    metadata_path = run_dir / "run_metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text())
        except Exception:
            metadata = {}
    metadata.update(updates)
    metadata_path.write_text(json.dumps(metadata, indent=2))
    return metadata


def _refresh_sweep_outputs(sweep_dir: Path | None, provider: str, model: str) -> None:
    if not sweep_dir:
        return
    _update_sweep_metadata_agent(sweep_dir, provider, model)
    _write_leaderboard_to_sweep(sweep_dir)
    _write_agent_context_cache(sweep_dir)
    write_sweep_overview(sweep_dir, agent_provider=provider, agent_model=model)


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
    if not model.lower().startswith("gpt-5"):
        raise ValueError(f"Refusing non-GPT-5 OpenAI model '{model}'")
    r = client.responses.create(model=model, max_output_tokens=8192, input=[{"role": "user", "content": prompt}])
    return r.output_text if hasattr(r, "output_text") and r.output_text else ""


def _generate_short_name(description: str, result: str, call_fn) -> str:
    """Ask the LLM for a 3-6 word descriptive name for this run."""
    prompt = (
        "Give a short descriptive name (3-6 words, no quotes, no punctuation) for this LLM serving optimization experiment.\n\n"
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


def _read_retro_summary(run_dir: Path) -> str:
    """Extract a one-line failure summary from RETRO.md (Change + Result)."""
    retro = run_dir / "RETRO.md"
    if not retro.exists():
        return ""
    try:
        text = retro.read_text(errors="replace")
    except Exception:
        return ""

    def _clean(s: str) -> str:
        s = s.replace("**", "").replace("`", "")
        s = s.strip("*-| ").strip()
        return s

    change = ""
    result = ""
    current_section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip().lower()
            continue
        if not stripped or stripped.startswith("|"):
            continue
        if current_section == "change" and not change:
            change = _clean(stripped)
        elif current_section == "result" and not result:
            result = _clean(stripped)
    parts = []
    if change:
        parts.append(change[:80])
    if result:
        parts.append(result[:80])
    return " → ".join(parts) if parts else ""


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


def _effective_deploy_hard_timeout(vllm_yaml: Path) -> int:
    """Return the deploy watchdog timeout for this config."""
    if os.environ.get("EXPERIMENT_DEPLOY_HARD_TIMEOUT"):
        return DEPLOY_HARD_TIMEOUT
    try:
        doc = yaml.safe_load(vllm_yaml.read_text()) or {}
        container = ((doc.get("spec") or {}).get("containers") or [{}])[0]
        args = "\n".join(container.get("args") or [])
        limits = (container.get("resources") or {}).get("limits") or {}
        gpu_count = int(limits.get("nvidia.com/gpu", 1))
        if "moonshotai/Kimi-K2.5" in args:
            return 1800
        if gpu_count >= 8 and "--load-format tensorizer" not in args and "--download-dir" in args:
            return 1200
    except Exception:
        pass
    return DEPLOY_HARD_TIMEOUT


def _check_abort(
    start: float,
    phase: str,
    last_progress: float | None = None,
    deploy_hard_timeout: int = DEPLOY_HARD_TIMEOUT,
) -> str | None:
    """Return abort message if we should abort, unless recent progress was made.

    For deploy/health phases: abort if no log activity for INSPECT_AFTER_SEC,
    or if deploy_hard_timeout is exceeded regardless of activity.
    For benchmark phase: uses last_progress (query count updates) with INSPECT_AFTER_SEC.
    """
    if INSPECT_AFTER_SEC <= 0:
        return None
    elapsed = _elapsed_since(start)
    if elapsed >= deploy_hard_timeout and phase != "benchmark":
        return f"Hard timeout after {int(elapsed)}s in phase '{phase}' (limit {deploy_hard_timeout}s)"
    if elapsed < INSPECT_AFTER_SEC:
        return None
    if last_progress is not None and (time.time() - last_progress) < INSPECT_AFTER_SEC:
        return None
    if last_progress is None and phase != "benchmark":
        return f"Aborted after {int(elapsed)}s: no activity for {INSPECT_AFTER_SEC}s in phase '{phase}'"
    return f"Aborted after {int(elapsed)}s: stuck in phase '{phase}'"


# Patterns indicating infrastructure/Kubernetes setup errors (NOT fixable by changing vLLM YAML)
INFRASTRUCTURE_ERROR_PATTERNS = [
    "Forbidden",
    "Error from server (Forbidden)",
    "connection refused",
    "dial tcp",
    "RBAC",
    "Unauthorized",
    "get current server API",
    "Pod unschedulable",
    "Unschedulable",
    "Insufficient nvidia.com/gpu",
]


def _is_infrastructure_error(result: str) -> bool:
    """Return True if the error is cluster/setup/capacity, not vLLM config."""
    r = result.lower()
    return any(p.lower() in r for p in INFRASTRUCTURE_ERROR_PATTERNS)


def _infrastructure_error_guidance(result: str) -> list[str]:
    """Actionable next steps for infra/capacity failures."""
    r = (result or "").lower()
    if "unschedulable" in r or "insufficient nvidia.com/gpu" in r:
        return [
            "This is a cluster-capacity issue, not a config problem. Check:",
            "  1. kubectl get pods -o wide  (confirm current GPU occupancy)",
            "  2. kubectl describe nodes  (confirm allocatable GPUs on the target pool)",
            "  3. Retry later or free capacity before spending another improve run",
        ]
    return [
        "This is a Kubernetes/kubectl setup issue. Check:",
        "  1. KUBECONFIG is set and points to your cluster",
        "  2. kubectl auth can-i delete pods  (must return yes)",
        "  3. kubectl get pods  (should reach the cluster)",
    ]


def _read_tail_if_exists(path: Path, limit: int = 6000) -> str:
    try:
        if path.exists():
            return path.read_text(errors="replace")[-limit:]
    except Exception:
        pass
    return ""


def _detect_retry_skip_reason(run_dir: Path, result: str) -> str | None:
    """Return a reason to skip another agent retry for known harness-only failures."""
    text = (result or "").lower()
    deploy_tail = _read_tail_if_exists(run_dir / "deploy.log")
    kubectl_tail = _read_tail_if_exists(run_dir / "kubectl_logs.txt")
    combined = f"{deploy_tail}\n{kubectl_tail}".lower()

    if "sample query returned empty or invalid response" in text:
        if '"reasoning_content"' in combined or '"reasoning"' in combined or '"content": null' in combined:
            return (
                "sample query failed because the model answered in reasoning fields; "
                "treat this as a harness/parser issue, not a new config experiment"
            )

    if "stuck in phase 'pod_wait'" in text or "stuck in phase 'health_check'" in text:
        if "traceback" not in combined and "runtimeerror:" not in combined and "error: unrecognized arguments" not in combined:
            if "condition met" in combined or "containersnotready" in combined or "readiness probe" in combined:
                return (
                    "watchdog timed out during pod readiness without a clear config crash; "
                    "inspect harness/k8s lifecycle instead of spending another agent retry"
                )

    if "no benchmark json found" in text and "post /v1/chat/completions" in combined:
        return (
            "benchmark traffic reached the server but artifacts were not captured; "
            "this looks like harness bookkeeping rather than a new tuning problem"
        )

    return None


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


def _k8s_label_value(value: str) -> str:
    """Sanitize a value for Kubernetes labels."""
    value = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower())
    value = value.strip("-.")
    return value[:63] or "default"


def _stable_base_pod_name(name: str) -> str:
    """Strip our run suffix so retries reuse the same canonical base name."""
    raw = (name or "").strip() or "vllm"
    stable = re.sub(r"(?:-\d{8})+$", "", raw)
    return stable or raw


def _sample_message_has_output(message: dict) -> bool:
    """Kimi may answer in reasoning fields even when content is null."""
    tool_calls = message.get("tool_calls") or []
    text_fields = [
        message.get("content"),
        message.get("reasoning"),
        message.get("reasoning_content"),
    ]
    has_text = any(isinstance(value, str) and bool(value.strip()) for value in text_fields)
    has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
    return has_text or has_tool_calls


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


def _capture_command_output(run_dir: Path, env: dict, filename: str, cmd: list[str], timeout: int = 30) -> None:
    """Best-effort capture of pod diagnostics before cleanup deletes the pod."""
    out_path = run_dir / filename
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        text = [
            f"command={' '.join(cmd)}",
            f"returncode={r.returncode}",
            "",
            r.stdout or "",
            "",
            "STDERR:",
            r.stderr or "",
        ]
    except Exception as exc:
        text = [f"command={' '.join(cmd)}", f"error={exc}"]
    out_path.write_text("\n".join(text))


def _capture_pod_debug(run_dir: Path, env: dict, pod_name: str) -> None:
    """Persist enough state to diagnose pod_wait/health_check failures after cleanup."""
    commands = [
        ("pod_get.json", ["kubectl", "get", "pod", pod_name, "-o", "json"]),
        ("pod_describe.txt", ["kubectl", "describe", "pod", pod_name]),
        (
            "pod_events.txt",
            [
                "kubectl",
                "get",
                "events",
                "--sort-by=.lastTimestamp",
                "--field-selector",
                f"involvedObject.name={pod_name}",
            ],
        ),
        ("pod_logs_current.txt", ["kubectl", "logs", pod_name, "--all-containers=true", "--tail=400"]),
        (
            "pod_logs_previous.txt",
            ["kubectl", "logs", pod_name, "--all-containers=true", "--previous", "--tail=400"],
        ),
    ]
    for filename, cmd in commands:
        _capture_command_output(run_dir, env, filename, cmd)


def _summarize_pod_state(pod_doc: dict) -> tuple[str, str | None]:
    """Return a concise pod status string plus any fatal lifecycle error."""
    status = pod_doc.get("status") or {}
    phase = str(status.get("phase") or "Unknown")
    summary_parts = [f"phase={phase}"]
    fatal_error: str | None = None

    pod_reason = str(status.get("reason") or "").strip()
    if pod_reason:
        summary_parts.append(f"reason={pod_reason}")
    if phase == "Failed" and not fatal_error:
        fatal_error = f"Pod entered Failed phase ({pod_reason or 'no reason reported'})"

    for cond in status.get("conditions") or []:
        cond_type = str(cond.get("type") or "")
        cond_status = str(cond.get("status") or "")
        cond_reason = str(cond.get("reason") or "").strip()
        if cond_type:
            label = f"{cond_type}={cond_status}"
            if cond_reason:
                label += f":{cond_reason}"
            summary_parts.append(label)
        if cond_type == "PodScheduled" and cond_status == "False" and cond_reason == "Unschedulable" and not fatal_error:
            message = str(cond.get("message") or "").strip()
            fatal_error = f"Pod unschedulable: {message[:300] or cond_reason}"

    fatal_waiting_reasons = {
        "CrashLoopBackOff",
        "CreateContainerConfigError",
        "CreateContainerError",
        "ErrImagePull",
        "ImageInspectError",
        "ImagePullBackOff",
        "InvalidImageName",
        "RunContainerError",
    }
    for container in status.get("containerStatuses") or []:
        name = str(container.get("name") or "container")
        state = container.get("state") or {}
        waiting = state.get("waiting")
        running = state.get("running")
        terminated = state.get("terminated")
        if isinstance(waiting, dict):
            reason = str(waiting.get("reason") or "Waiting")
            summary_parts.append(f"{name}=waiting:{reason}")
            if reason in fatal_waiting_reasons and not fatal_error:
                message = str(waiting.get("message") or "").strip()
                fatal_error = f"Container {name} waiting: {reason}: {message[:300] or reason}"
        elif isinstance(running, dict):
            summary_parts.append(f"{name}=running")
        elif isinstance(terminated, dict):
            exit_code = terminated.get("exitCode")
            reason = str(terminated.get("reason") or "Terminated")
            summary_parts.append(f"{name}=terminated:{reason}:{exit_code}")
            if exit_code not in (None, 0) and not fatal_error:
                fatal_error = f"Container {name} terminated with exit code {exit_code} ({reason})"

    return " | ".join(summary_parts), fatal_error


def _capture_pod_status(run_dir: Path, env: dict, pod_name: str, status_file: Path) -> tuple[str | None, str | None]:
    """Snapshot current pod status so pod_wait can track lifecycle progress without logs."""
    try:
        r = subprocess.run(
            ["kubectl", "get", "pod", pod_name, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except Exception:
        return None, None
    if r.returncode != 0:
        return None, None
    try:
        pod_doc = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return None, None
    summary, fatal_error = _summarize_pod_state(pod_doc)
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "pod_name": pod_name,
        "summary": summary,
        "phase": ((pod_doc.get("status") or {}).get("phase") or "Unknown"),
    }
    with open(status_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot) + "\n")
    return summary, fatal_error


def _deploy_and_benchmark(
    experiment_dir: Path, benchmark: str, run_dir: Path, ts: str, sweep: str | None = None
) -> tuple[bool, str]:
    """Deploy from experiment_dir, run benchmark, stream logs to run_dir, track queries, abort if stuck.
    Uses a unique pod name and local port so multiple runs can execute in parallel."""
    start = time.time()
    vllm_yaml = experiment_dir / "vllm-config.yaml"
    deploy_hard_timeout = _effective_deploy_hard_timeout(vllm_yaml)
    env = os.environ.copy()
    env["VLLM_CONFIG"] = str(vllm_yaml)
    env["KUBECONFIG"] = os.environ.get("KUBECONFIG", "")
    logs_proc = None
    profiler: VLLMProfiler | None = None
    diagnostics_captured = False

    # Unique pod name for parallel runs
    short_id = ts.replace("_", "")[-8:]
    base_pod = "vllm"
    try:
        _doc = yaml.safe_load(vllm_yaml.read_text())
        base_pod = _doc.get("metadata", {}).get("name", "vllm") or "vllm"
    except Exception:
        pass
    base_pod = _stable_base_pod_name(base_pod)
    pod_name = f"{base_pod}-{short_id}"
    _rewrite_pod_name(vllm_yaml, pod_name, sweep=sweep)
    _log_run(run_dir, f"Pod: {pod_name}")
    _log_run(run_dir, f"Deploy hard timeout: {deploy_hard_timeout}s")

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
        nonlocal diagnostics_captured
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
        if logs_proc and logs_proc.poll() is None:
            logs_proc.terminate()
            try:
                logs_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logs_proc.kill()
        if msg and not diagnostics_captured:
            try:
                _capture_pod_debug(run_dir, env, pod_name)
            except Exception:
                pass
            diagnostics_captured = True
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

    # Delete both the new pod name AND the base pod (from baseline) to free GPUs
    delete_cmds: list[tuple[list[str], str]] = [
        (["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true"], "delete failed"),
    ]
    if base_pod != pod_name:
        delete_cmds.insert(0, (["kubectl", "delete", "pod", base_pod, "--ignore-not-found=true", "--wait=false"], "base pod delete failed"))
    for cmd, err in [
        *delete_cmds,
        (["kubectl", "apply", "-f", str(vllm_yaml)], "apply failed"),
    ]:
        if m := _check_abort(start, "deploy", deploy_hard_timeout=deploy_hard_timeout):
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
    pod_status_file = run_dir / "pod_status.jsonl"
    pod_status_file.write_text("")

    _write_progress("pod_wait", {})
    _log_run(run_dir, "Waiting for pod Ready...")
    last_pod_activity = time.time()
    prev_pod_log_size = 0
    prev_pod_summary: str | None = None
    for _ in range(20):
        if m := _check_abort(
            start,
            "pod_wait",
            last_progress=last_pod_activity,
            deploy_hard_timeout=deploy_hard_timeout,
        ):
            return _cleanup(m)
        if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
            return _cleanup(f"vLLM startup error (pod_wait): {err}")
        cur_pod_log_size = kubectl_logs_file.stat().st_size if kubectl_logs_file.exists() else 0
        if cur_pod_log_size > prev_pod_log_size:
            last_pod_activity = time.time()
            prev_pod_log_size = cur_pod_log_size
        pod_summary, pod_error = _capture_pod_status(run_dir, env, pod_name, pod_status_file)
        if pod_summary:
            last_pod_activity = time.time()
            if pod_summary != prev_pod_summary:
                prev_pod_summary = pod_summary
                _log_run(run_dir, f"Pod status: {pod_summary}")
        if pod_error:
            return _cleanup(f"Pod startup error (pod_wait): {pod_error}")
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
    last_log_activity = time.time()
    prev_log_size = kubectl_logs_file.stat().st_size if kubectl_logs_file.exists() else 0
    for i in range(900):
        if m := _check_abort(
            start,
            "health_check",
            last_progress=last_log_activity,
            deploy_hard_timeout=deploy_hard_timeout,
        ):
            return _cleanup(m)
        if i % 5 == 4:
            if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
                return _cleanup(f"vLLM startup error (health_check): {err}")
            cur_log_size = kubectl_logs_file.stat().st_size if kubectl_logs_file.exists() else 0
            if cur_log_size > prev_log_size:
                last_log_activity = time.time()
                prev_log_size = cur_log_size
                elapsed = time.time() - health_start
                if int(elapsed) % 60 < 12:
                    _log_run(run_dir, f"vLLM still starting ({elapsed:.0f}s, logs active)...")
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
        extracted_model = _extract_model_identity(text)
        if extracted_model:
            model = extracted_model
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
        message = (data.get("choices") or [{}])[0].get("message", {}) or {}
        if not _sample_message_has_output(message):
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

    with open(kubectl_logs_file, "a", encoding="utf-8") as f:
        f.write(f"\n--- live stream started {datetime.now().isoformat()} ---\n")
    logs_proc = subprocess.Popen(
        ["kubectl", "logs", "-f", pod_name, "--all-containers=true"],
        stdout=open(kubectl_logs_file, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=env,
    )

    _write_progress("benchmark", {"run_dir": str(run_dir)})
    _log_run(run_dir, f"Starting benchmark ({benchmark}) as K8s Job, run_dir={run_dir}")

    cfg = BENCHMARK_PRESETS.get(benchmark, BENCHMARK_PRESETS["quick"])
    bench_config = {
        "profile": cfg["profile"],
        "max_requests": cfg["max_requests"],
        "max_seconds": cfg["max_seconds"],
        "rate": cfg.get("rate"),
        "data": cfg["data"],
    }
    if "--trust-remote-code" in vllm_yaml.read_text():
        bench_config["processor_args"] = {"trust_remote_code": True}

    max_requests = BENCHMARK_MAX_REQUESTS.get(benchmark, 0)
    bench_start = time.time()
    last_queries = [0]

    def _progress_cb(completed: int) -> None:
        if completed > last_queries[0]:
            last_queries[0] = completed
            _write_progress("benchmark", {
                "run_dir": str(run_dir),
                "queries_completed": completed,
                "last_progress": datetime.now().isoformat(),
            })
            elapsed = time.time() - bench_start
            if max_requests > 0 and completed > 0:
                pct = min(completed / max_requests, 1.0)
                bar_width = 30
                filled = int(bar_width * pct)
                bar = "█" * filled + "░" * (bar_width - filled)
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (max_requests - completed) / rate if rate > 0 else 0
                print(f"\r  [{bar}] {completed}/{max_requests} ({pct*100:.0f}%) | {rate:.1f} req/s | ETA {eta:.0f}s", end="", flush=True)
            else:
                print(f"\r  {completed} requests | {elapsed:.0f}s elapsed", end="", flush=True)

    try:
        bench_rc = run_benchmark_k8s(
            pod_name=pod_name,
            config=bench_config,
            run_dir=run_dir,
            env=env,
            log_fn=lambda msg: _log_run(run_dir, msg),
            progress_callback=_progress_cb,
        )
    except Exception as e:
        return _cleanup(f"Benchmark error: {e}")
    finally:
        if logs_proc and logs_proc.poll() is None:
            logs_proc.terminate()
            try:
                logs_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logs_proc.kill()

    if last_queries[0] > 0:
        print()

    if bench_rc != 0:
        _cleanup()
        return False, f"Benchmark failed (K8s Job exit {bench_rc}). See {run_dir}/benchmark_live.txt"

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
        provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
        model = effective_agent_model(provider, os.environ.get("AI_MODEL", ""))
        _refresh_sweep_outputs(sweep_dir, provider, model)
        print(f"Wrote {sweep_dir / 'leaderboard.txt'}")
        return 0

    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    model = os.environ.get("AI_MODEL", "")
    if provider == "anthropic":
        model = model or effective_agent_model(provider)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY"); return 1
        call_fn = lambda p: _call_anthropic(p, model)
    elif provider == "openai":
        model = model or effective_agent_model(provider)
        if not os.environ.get("OPENAI_API_KEY"):
            print("Set OPENAI_API_KEY"); return 1
        if not model.lower().startswith("gpt-5"):
            print(f"Refusing to use non-GPT-5 OpenAI model '{model}'. Use GPT-5.4/latest GPT, or switch to Anthropic.")
            return 1
        call_fn = lambda p: _call_openai(p, model)
    else:
        print("AI_PROVIDER must be 'anthropic' or 'openai'"); return 1

    if not RUNLLM.exists():
        print("runllm submodule not found"); return 1

    if sweep_dir:
        _refresh_sweep_outputs(sweep_dir, provider, model)
        stop_status = should_stop_sweep(sweep_dir)
        if stop_status["stop"]:
            print(stop_status["reason"])
            return SWEEP_STOP_EXIT_CODE

    # Determine which model subdir to use
    model_dir = DEFAULT_MODEL_DIR
    model_variants: list[str] = []
    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            _sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            model_dir = _sm.get("model_dir", DEFAULT_MODEL_DIR)
            model_variants = list(_sm.get("model_variants") or [])
        except Exception:
            pass
    if not model_variants:
        model_variants = list_model_variants(RUNLLM, model_dir)
    if not model_variants:
        model_variants = [model_dir]
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
    current_backend = infer_backend(vllm_content, makefile_content)
    backend_templates = _load_backend_templates(RUNLLM, model_variants)
    if backend_from_model_dir(model_dir) != "vllm":
        backend_templates = [t for t in backend_templates if t["backend"] == current_backend]
    backend_templates_section = _render_backend_templates_section(backend_templates)
    # Ensure experiment_dir always uses the new name
    (experiment_dir / "vllm-config.yaml").write_text(vllm_content)
    runs_for_context = sweep_dir or RUNS_DIR
    leaderboard = _get_experiment_leaderboard(
        runs_for_context,
        PROJECT_ROOT,
        max_successes=PROMPT_LEADERBOARD_SUCCESS_LIMIT,
        max_failures=PROMPT_LEADERBOARD_FAILURE_LIMIT,
        compact=True,
    )
    if sweep_dir:
        _get_or_refresh_research_memory(sweep_dir, call_fn)
        _write_leaderboard_to_sweep(sweep_dir)
        _write_agent_context_cache(sweep_dir)
    workload = _get_workload_description(runs_for_context)
    profile_context = _get_profile_context(runs_for_context, PROJECT_ROOT)
    known_issues_section = _build_known_issues_section(runs_for_context)
    research_memory_section = ""
    if sweep_dir:
        research_memory = _get_or_refresh_research_memory(sweep_dir, call_fn)
        if research_memory:
            research_memory_section = (
                "\n## Sweep research memory (read this before doing more web research)\n\n"
                f"{research_memory[:PROMPT_RESEARCH_MEMORY_CHAR_LIMIT]}\n"
            )

    # Include the most recent run retro alongside the synthesized summary.
    latest_retro_section = ""
    if sweep_dir:
        latest_run_name, latest_retro = _get_latest_retro(sweep_dir)
        if latest_retro:
            latest_retro_section = (
                f"\n## Most recent run retro ({latest_run_name})\n\n"
                f"{latest_retro[:1800]}\n"
            )

    # Reuse cached FULL_RETRO.txt unless the sweep meaningfully changed.
    full_retro_section = ""
    if sweep_dir:
        full_retro = _get_or_refresh_full_retro(sweep_dir, call_fn)
        if full_retro:
            full_retro_section = f"\n## Lessons learned from all previous runs\n\n{full_retro[:2400]}\n"
    elif runs_for_context and runs_for_context.exists():
        raw = _collect_all_retros(runs_for_context)
        if raw:
            full_retro_section = f"\n## Lessons from previous runs\n\n{raw[:1800]}\n"

    # Read optional meta-feedback (human/external-model suggestions)
    meta_feedback_section = ""
    meta_feedback_file = (sweep_dir or runs_for_context) / "meta-feedback.txt"
    if meta_feedback_file.exists():
        try:
            fb = meta_feedback_file.read_text().strip()
            if fb:
                meta_feedback_section = (
                    "\n## Meta-feedback (external reviewer)\n\n"
                    f"{fb[:1200]}\n"
                )
        except Exception:
            pass

    high_leverage_knobs_section = """
## High-leverage knobs

- Batching/scheduling: `--max-num-batched-tokens`, `--max-num-seqs`, `--enable-chunked-prefill`, `--max-num-partial-prefills`, `--async-scheduling`
- Memory/context: `--gpu-memory-utilization`, `--kv-cache-dtype`, `--block-size`, `--max-model-len`
- Precision/compile: `--dtype`, `--quantization`, `--compilation-config`, `--enforce-eager`
- Caching/speculation: `--enable-prefix-caching`; speculative decoding only if already validated on this backend
"""

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
    has_multiple_backends = len({t["backend"] for t in backend_templates}) > 1
    vllm_templates = [t for t in backend_templates if t["backend"] == "vllm"]
    sglang_templates = [t for t in backend_templates if t["backend"] == "sglang"]
    current_backend_label = current_backend
    backend_constraint_lines = [
        "- Keep `apiVersion: v1` and `kind: Pod`. Do NOT change `metadata.name`, `restartPolicy`, `--host`, or `--port`.",
    ]
    if has_multiple_backends:
        backend_constraint_lines.append(
            f"- Current backend: `{current_backend_label}`. You MAY switch only between these canonical variants: "
            + ", ".join(f"`{t['model_dir']}` ({t['backend']})" for t in backend_templates)
            + ". Do NOT invent a new backend or custom image."
        )
        backend_constraint_lines.append(
            "- If you switch backend, copy both `vllm-config.yaml` and `Makefile` from the chosen canonical variant first. "
            "A backend switch is the single experiment change for the run."
        )
    else:
        backend_constraint_lines.append(f"- Keep the current backend scaffold exactly as-is (`{current_backend_label}`).")
    if vllm_templates:
        backend_constraint_lines.extend([
            "- For any vLLM variant, preserve the `command:`/`args:` init script, `volumeMounts:`, and `volumes:` exactly as-is. "
            "Only modify the `vllm serve` flags after `exec vllm serve`, unless the experiment is an explicit backend switch.",
            "- For any vLLM variant, do NOT change `--load-format`, `--model-loader-extra-config`, `--served-model-name`, or the tensorized model path.",
            "- For any vLLM variant, `--disable-log-requests` and `--num-scheduler-steps` do NOT exist in this image.",
            "- For any vLLM variant, do NOT use `--disable-log-stats`. Logs and metrics are needed for diagnosis.",
        ])
    if sglang_templates:
        backend_constraint_lines.extend([
            "- For any SGLang variant, keep the canonical `sglang serve` launcher structure and image family. "
            "Do not replace it with a custom wrapper or a different serving stack unless the experiment is switching back to another canonical variant.",
            "- For any SGLang variant, keep the served model name aligned with `VLLM_MODEL` in the Makefile.",
        ])
    backend_quirk_lines = [
        "- Diagnose from evidence (leaderboard, logs), not assumptions. Many successful `POST /v1/chat/completions` in logs = benchmark progress, likely a harness/watchdog issue not a config failure.",
    ]
    if vllm_templates:
        backend_quirk_lines.extend([
            "- `VLLM_ATTENTION_BACKEND` env var warns \"Unknown vLLM environment variable\". Do NOT introduce it if absent; only change it as a dedicated experiment if already present.",
            "- `--performance-mode` has failed before. Do NOT introduce unless already in a successful leaderboard run.",
            "- `draft_model` speculative decoding is broken on this vLLM nightly with our tensorized main model. Do NOT propose draft-model speculation, even with `draft_load_config.load_format=auto`.",
            "- If you try speculative decoding on vLLM, use ngram only and use dot-notation CLI args (`--speculative-config.method ngram`, etc.), not JSON blob syntax.",
        ])
    if sglang_templates:
        backend_quirk_lines.append(
            "- SGLang serves the same OpenAI-compatible chat endpoint used by the harness. If you switch to SGLang, benchmark compatibility depends on preserving `/health` and `/v1/chat/completions`."
        )
    backend_constraints_section = "\n- ".join(backend_constraint_lines)
    backend_quirks_section = "\n- ".join(backend_quirk_lines)

    prompt = f"""You are optimizing LLM inference on Kubernetes (H200 GPU, CoreWeave).

**Hardware:** {hardware_desc}
**Benchmark workload:** {workload}
**Goal:** {goal}
**Current backend:** {current_backend_label}

## Current best config (your baseline to improve on)

```yaml
{vllm_content}
```

## Experiment leaderboard

{leaderboard}
{known_issues_section}{research_memory_section}{profile_context}{latest_retro_section}{full_retro_section}{meta_feedback_section}{backend_templates_section}
## Hard constraints (DO NOT violate)

- {backend_constraints_section}
{"- Do NOT change the --model (model changes not enabled for this sweep)" if not allow_model_change else ""}
{model_change_section}
## Observed quirks

- {backend_quirks_section}
{high_leverage_knobs_section}
## Your task

Pick ONE untried change (check leaderboard) backed by evidence. Change exactly one knob.
This run should test exactly one experiment hypothesis. If that hypothesis benchmarks successfully, stop even if it regresses.
Prefer local evidence from the sweep. Read the sweep research memory first. Only use `search_web`/`fetch_url` when that memory plus the logs/retros do not already cover the question.
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

    initial_backend = infer_backend_from_runllm_dir(experiment_dir)
    _update_run_metadata(
        run_dir,
        timestamp=ts,
        description="",
        backend=initial_backend,
        model_dir=model_dir,
        model_variants=model_variants,
        experiment_dir=str(experiment_dir),
        benchmark=benchmark,
        sweep=sweep or None,
        agent_provider=provider,
        agent_model=model,
        success=False,
        result="",
        failure_classification={"is_unfixable": False, "category": "pending", "matched_text": "", "summary": ""},
    )
    if sweep_dir:
        write_sweep_overview(sweep_dir, agent_provider=provider, agent_model=model)

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
                print()
                for line in _infrastructure_error_guidance(result_msg):
                    print(line)
                _update_run_metadata(
                    run_dir,
                    description="Infrastructure error",
                    attempt=attempt + 1,
                    success=False,
                    result=result_msg[:1000],
                    failure_classification=classify_failure_text(result_msg),
                )
                if sweep_dir:
                    _refresh_sweep_outputs(sweep_dir, provider, model)
                    stop_status = should_stop_sweep(sweep_dir)
                    if stop_status["stop"]:
                        print(stop_status["reason"])
                        return SWEEP_STOP_EXIT_CODE
                return 1

            retry_skip_reason = _detect_retry_skip_reason(run_dir, result_msg)
            if retry_skip_reason:
                stop_msg = f"Stopping retries: {retry_skip_reason}"
                print(stop_msg)
                _update_run_metadata(
                    run_dir,
                    description=stop_msg[:500],
                    attempt=attempt + 1,
                    success=False,
                    result=result_msg[:1000],
                    failure_classification=classify_failure_text(result_msg),
                )
                _append_result(
                    experiment_dir,
                    stop_msg,
                    result_msg,
                    success=False,
                    run_dir=run_dir,
                    results_path=results_txt,
                )
                if sweep_dir:
                    _refresh_sweep_outputs(sweep_dir, provider, model)
                    stop_status = should_stop_sweep(sweep_dir)
                    if stop_status["stop"]:
                        print(stop_status["reason"])
                        return SWEEP_STOP_EXIT_CODE
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
- Prefer local retros/logs/research memory over web search. Only use `search_web`/`fetch_url` for genuinely new flags or undocumented crashes.
- Otherwise fix minimally: repair the failed experiment only, reverting the last change first if needed.
- Keep Pod kind. Do not invent a new backend or image family; only use the canonical variants for this sweep if you must switch backends.
- For vLLM variants, preserve the init script, PVC volumeMounts/volumes, and tensorizer flags exactly as-is. Only modify `vllm serve` flags.
- For SGLang variants, preserve the canonical `sglang serve` launcher shape and keep `/health` plus `/v1/chat/completions` compatible with the harness.
- No `--disable-log-requests` (doesn't exist for vLLM here). No `--disable-log-stats` (logs/metrics needed for diagnosis). No `VLLM_ATTENTION_BACKEND` if absent.

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
            err_msg = f"Agent error: {e}"
            print(err_msg)
            classification = classify_failure_text(err_msg)
            _update_run_metadata(
                run_dir,
                description=err_msg[:500],
                attempt=attempt + 1,
                tools_used=0,
                success=False,
                result=err_msg[:1000],
                failure_classification=classification,
            )
            _append_result(experiment_dir, err_msg, "", results_path=results_txt)
            if sweep_dir:
                _refresh_sweep_outputs(sweep_dir, provider, model)
                stop_status = should_stop_sweep(sweep_dir)
                if stop_status["stop"]:
                    print(stop_status["reason"])
                    return SWEEP_STOP_EXIT_CODE
            return 1

        _write_agent_result_log(run_dir, agent_result, sweep_dir)

        if agent_result.error:
            err_msg = f"Agent loop error: {agent_result.error}"
            print(err_msg)
            classification = classify_failure_text(err_msg)
            _update_run_metadata(
                run_dir,
                description=err_msg[:500],
                attempt=attempt + 1,
                tools_used=len(agent_result.tool_log),
                success=False,
                result=agent_result.error[:1000],
                failure_classification=classification,
            )
            _append_result(experiment_dir, agent_result.error, "", results_path=results_txt)
            if sweep_dir:
                _refresh_sweep_outputs(sweep_dir, provider, model)
                stop_status = should_stop_sweep(sweep_dir)
                if stop_status["stop"]:
                    print(stop_status["reason"])
                    return SWEEP_STOP_EXIT_CODE
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
                    _update_run_metadata(
                        run_dir,
                        description=stop_msg[:500],
                        attempt=attempt + 1,
                        tools_used=len(agent_result.tool_log),
                        success=False,
                        result=(failure_context or {}).get("result", "")[:1000],
                        failure_classification=classify_failure_text((failure_context or {}).get("result", "")),
                    )
                    _append_result(
                        experiment_dir,
                        stop_msg,
                        (failure_context or {}).get("result", ""),
                        success=False,
                        run_dir=run_dir,
                        results_path=results_txt,
                    )
                    if sweep_dir:
                        _refresh_sweep_outputs(sweep_dir, provider, model)
                        stop_status = should_stop_sweep(sweep_dir)
                        if stop_status["stop"]:
                            print(stop_status["reason"])
                            return SWEEP_STOP_EXIT_CODE
                    return 1
                yaml_content = (experiment_dir / "vllm-config.yaml").read_text()
                description = f"No config change: {no_config_change_reason}"
            elif yaml_content:
                description = agent_result.description or _extract_description(agent_result.text)
            else:
                description = _extract_description(agent_result.text)
                err = "Could not extract YAML from agent response"
                print(err)
                classification = classify_failure_text(err)
                _update_run_metadata(
                    run_dir,
                    description=description[:500],
                    attempt=attempt + 1,
                    tools_used=len(agent_result.tool_log),
                    success=False,
                    result=err,
                    failure_classification=classification,
                )
                _append_result(experiment_dir, description, err, results_path=results_txt)
                if sweep_dir:
                    _refresh_sweep_outputs(sweep_dir, provider, model)
                    stop_status = should_stop_sweep(sweep_dir)
                    if stop_status["stop"]:
                        print(stop_status["reason"])
                        return SWEEP_STOP_EXIT_CODE
                return 1

        # Validate: revert unauthorized model changes
        if not allow_model_change and yaml_content:
            baseline_model = _extract_model_identity(vllm_content)
            proposed_model = _extract_model_identity(yaml_content)
            if baseline_model and proposed_model and proposed_model != baseline_model:
                print(f"Agent tried to change model to {proposed_model} — reverting to {baseline_model}")
                yaml_content = yaml_content.replace(proposed_model, baseline_model)

        last_description = description

        if not agent_result.config_written:
            (experiment_dir / "vllm-config.yaml").write_text(yaml_content)
            shutil.copy(experiment_dir / "vllm-config.yaml", run_dir / "vllm_config.yaml")
            makefile_new = _extract_makefile(agent_result.text) or (experiment_dir / "Makefile").read_text()
            (experiment_dir / "Makefile").write_text(makefile_new)

        run_backend = infer_backend_from_runllm_dir(experiment_dir)
        _update_run_metadata(
            run_dir,
            timestamp=ts,
            description=description[:500],
            backend=run_backend,
            model_dir=model_dir,
            model_variants=model_variants,
            experiment_dir=str(experiment_dir),
            benchmark=benchmark,
            sweep=sweep or None,
            attempt=attempt + 1,
            tools_used=len(agent_result.tool_log),
            agent_provider=provider,
            agent_model=model,
        )

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

        failure_classification = (
            {"is_unfixable": False, "category": "success", "matched_text": "", "summary": ""}
            if success else classify_failure_text(result)
        )
        _update_run_metadata(
            run_dir,
            success=success,
            result=result[:1000],
            failure_classification=failure_classification,
            attempt=attempt + 1,
            tools_used=len(agent_result.tool_log),
        )
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
                _refresh_sweep_outputs(sweep_dir, provider, model)
            print(f"Results: {result}")
            return 0

        # Gather failure context for retry
        failure_context = {"result": result}
        print(f"Attempt {attempt + 1} failed: {result[:200]}...")

    # Exhausted retries
    _append_result(experiment_dir, last_description, f"Failed after {max_attempts} attempts. Last error: {(failure_context or {}).get('result', '')}", success=False, run_dir=run_dir, results_path=results_txt)
    if sweep_dir:
        final_result = (failure_context or {}).get("result", "")[:1000]
        _update_run_metadata(
            run_dir,
            success=False,
            result=final_result,
            failure_classification=classify_failure_text(final_result),
        )
        _refresh_sweep_outputs(sweep_dir, provider, model)
        stop_status = should_stop_sweep(sweep_dir)
        if stop_status["stop"]:
            print(stop_status["reason"])
            return SWEEP_STOP_EXIT_CODE
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
    run_dir.mkdir(parents=True, exist_ok=True)
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
    model = os.environ.get("AI_MODEL", "gpt-5.4")
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
