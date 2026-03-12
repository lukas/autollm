#!/usr/bin/env python3
"""
Sweep utilities: best-runllm symlink, scoring.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def _score_run(run_dir: Path, sweep_name: str) -> float | None:
    """Score a run for 'best' (higher is better). Returns None if unscoreable."""
    bench_file = run_dir / "benchmarks.json"
    if not bench_file.exists():
        return None
    try:
        data = json.loads(bench_file.read_text())
        benchmarks = data.get("benchmarks") or []
        if not benchmarks:
            return None
        b = benchmarks[0]
        m = b.get("metrics", {})
        # Extract from nested structure: metrics.<metric>.<successful>.<mean>
        def _mean(k: str, sub: str = "successful") -> float | None:
            o = m.get(k, {})
            if not isinstance(o, dict):
                return None
            s = o.get(sub, o)
            if not isinstance(s, dict):
                return None
            v = s.get("mean")
            return float(v) if v is not None else None

        latency = _mean("request_latency")  # seconds
        ttft = _mean("time_to_first_token_ms")  # ms
        throughput = _mean("tokens_per_second")

        # Sweep name hints objective: latency -> lower is better, throughput -> higher
        name_lower = sweep_name.lower()
        if "latency" in name_lower:
            # Score = -latency (lower latency = higher score)
            if latency is not None:
                return -latency
            if ttft is not None:
                return -ttft / 1000
        if "throughput" in name_lower:
            if throughput is not None:
                return throughput

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
