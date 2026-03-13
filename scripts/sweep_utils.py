#!/usr/bin/env python3
"""
Sweep utilities: best-runllm symlink, scoring.
"""
from __future__ import annotations

import json
from pathlib import Path

from benchmark_config import BENCHMARK_MAX_REQUESTS

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

MIN_REQUEST_FRACTION = 0.5


def sweep_objective(sweep_name: str) -> str:
    """Infer the primary optimization objective from the sweep name."""
    name_lower = sweep_name.lower()
    if "latency" in name_lower:
        return "latency"
    if "throughput" in name_lower:
        return "throughput"
    if "ttft" in name_lower:
        return "ttft"
    return "composite"


def sweep_ranking_label(sweep_name: str) -> str:
    objective = sweep_objective(sweep_name)
    if objective == "latency":
        return "latency (lower is better)"
    if objective == "throughput":
        return "throughput (higher is better)"
    if objective == "ttft":
        return "TTFT (lower is better)"
    return "overall score"


def metric_mean(metrics: dict, key: str, sub: str = "successful") -> float | None:
    """Extract metrics.<key>.<sub>.mean from a Guideline metrics dict."""
    obj = metrics.get(key, {})
    if not isinstance(obj, dict):
        return None
    selected = obj.get(sub, obj)
    if not isinstance(selected, dict):
        return None
    value = selected.get("mean")
    return float(value) if value is not None else None


def completed_request_count(bench_data: dict) -> int:
    """Extract the number of completed requests from a parsed benchmarks.json."""
    benchmarks = bench_data.get("benchmarks") or []
    if not benchmarks:
        return 0
    m = benchmarks[0].get("metrics", {})
    rl = m.get("request_latency", {})
    if isinstance(rl, dict):
        sub = rl.get("successful", rl)
        if isinstance(sub, dict) and "count" in sub:
            return int(sub["count"])
    return 0


def expected_request_count(run_dir: Path) -> int:
    """Read the benchmark preset from run_metadata.json and return expected requests."""
    meta_file = run_dir / "run_metadata.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            preset = meta.get("benchmark", "")
            return BENCHMARK_MAX_REQUESTS.get(preset, 0)
        except Exception:
            pass
    return 0


def is_valid_run(run_dir: Path, bench_data: dict) -> bool:
    """A run is valid only if it completed enough requests relative to its preset."""
    completed = completed_request_count(bench_data)
    expected = expected_request_count(run_dir)
    if expected > 0:
        return completed >= expected * MIN_REQUEST_FRACTION
    return completed >= 10


def _score_run(run_dir: Path, sweep_name: str) -> float | None:
    """Score a run for 'best' (higher is better). Returns None if unscoreable."""
    bench_file = run_dir / "benchmarks.json"
    if not bench_file.exists():
        return None
    try:
        data = json.loads(bench_file.read_text())
        if not is_valid_run(run_dir, data):
            return None
        benchmarks = data.get("benchmarks") or []
        if not benchmarks:
            return None
        b = benchmarks[0]
        m = b.get("metrics", {})
        latency = metric_mean(m, "request_latency")  # seconds
        ttft = metric_mean(m, "time_to_first_token_ms")  # ms
        throughput = metric_mean(m, "tokens_per_second")

        objective = sweep_objective(sweep_name)
        if objective == "latency":
            # Score = -latency (lower latency = higher score)
            if latency is not None:
                return -latency
            if ttft is not None:
                return -ttft / 1000
        if objective == "throughput":
            if throughput is not None:
                return throughput
        if objective == "ttft":
            if ttft is not None:
                return -ttft / 1000

        # Default: composite — favor higher throughput, lower latency
        score = 0.0
        if throughput is not None:
            score += throughput
        if latency is not None:
            score -= latency * 100  # penalty for latency
        if ttft is not None:
            score -= ttft / 10
        return score
    except Exception:
        return None


def update_best_runllm(sweep_dir: Path, runllm_submodule: Path) -> None:
    """
    Find the best run in sweep_dir (by throughput/latency per sweep name),
    ensure it has runllm/, and create/update sweep_dir/best-runllm symlink.
    """
    if not sweep_dir.exists():
        return
    sweep_name = sweep_dir.name.replace("sweep-", "")
    best_dir: Path | None = None
    best_score: float = float("-inf")

    # Candidate dirs: baseline, and timestamp dirs
    for d in sweep_dir.iterdir():
        if not d.is_dir():
            continue
        if d.name.startswith("."):
            continue
        runllm_path = d / "runllm"
        if not runllm_path.exists():
            # Baseline might not have runllm yet; create from submodule
            if d.name == "baseline" and (d / "benchmarks.json").exists():
                import shutil
                shutil.copytree(runllm_submodule, runllm_path, ignore=shutil.ignore_patterns(".git"))
        if not runllm_path.exists():
            continue
        sc = _score_run(d, sweep_name)
        if sc is not None and sc > best_score:
            best_score = sc
            best_dir = d

    if best_dir is None:
        return
    target = best_dir / "runllm"
    link_path = sweep_dir / "best-runllm"
    if link_path.exists():
        link_path.unlink()
    rel = target.relative_to(sweep_dir)
    link_path.symlink_to(rel)
