#!/usr/bin/env python3
"""
Start a new sweep: create results/sweep-[name]/, run baseline benchmark, save to baseline/.

Usage:
  python scripts/start_sweep.py --sweep my-sweep --benchmark quick
  python scripts/start_sweep.py --sweep qwen3-235b --model-dir qwen3-235b --benchmark medium
  make sweep SWEEP=my-sweep BENCHMARK=quick
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from benchmark_config import BENCHMARK_PRESETS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNLLM_ROOT = PROJECT_ROOT / "runllm"
DEFAULT_MODEL_DIR = "qwen2.5-1.5b"


def _list_model_dirs() -> list[str]:
    """List available model subdirs under runllm/."""
    if not RUNLLM_ROOT.exists():
        return []
    return sorted(
        d.name for d in RUNLLM_ROOT.iterdir()
        if d.is_dir() and (d / "vllm-config.yaml").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Start a new sweep and run baseline")
    parser.add_argument("--sweep", "-s", required=True, help="Sweep name (e.g. qwen-1b-latency)")
    parser.add_argument(
        "--model-dir", "-m",
        default=DEFAULT_MODEL_DIR,
        help=f"Model subdirectory under runllm/ (available: {', '.join(_list_model_dirs()) or '?'})",
    )
    parser.add_argument(
        "--benchmark", "-b",
        choices=list(BENCHMARK_PRESETS),
        default="quick",
        help="Benchmark preset: quick, sync, sweep, medium, or long",
    )
    parser.add_argument(
        "--data",
        help="Override data config (e.g. prompt_tokens=64,output_tokens=64)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-run baseline even if it exists (overwrites)",
    )
    parser.add_argument("--max-requests", type=int, help="Override max requests")
    parser.add_argument("--max-seconds", type=float, help="Override max seconds")
    parser.add_argument("--goal", help="Optimization goal for the AI agent (e.g. 'minimize latency', 'maximize throughput', 'minimize TTFT')")
    args = parser.parse_args()

    name = args.sweep.strip().lower().replace(" ", "-")
    if not name:
        print("Sweep name required. Usage: make sweep SWEEP=my-sweep")
        return 1

    model_dir = args.model_dir
    model_path = RUNLLM_ROOT / model_dir
    if not (model_path / "vllm-config.yaml").exists():
        avail = _list_model_dirs()
        print(f"Model dir '{model_dir}' not found (no vllm-config.yaml). Available: {', '.join(avail)}")
        return 1

    sweep_dir = PROJECT_ROOT / "results" / f"sweep-{name}"
    baseline_dir = sweep_dir / "baseline"
    baseline_complete = baseline_dir.exists() and (baseline_dir / "benchmarks.json").exists()
    if baseline_complete and not args.force:
        print(f"Sweep '{name}' has a complete baseline. Use 'make improve SWEEP={name}' or add --force to re-run baseline.")
        return 1

    sweep_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)

    sweep_metadata = {
        "name": name,
        "model_dir": model_dir,
        "created_at": datetime.now().isoformat(),
        "benchmark": args.benchmark,
        "data": args.data,
        "max_requests": args.max_requests,
        "max_seconds": args.max_seconds,
        "goal": args.goal,
    }
    (sweep_dir / "sweep_metadata.json").write_text(json.dumps(sweep_metadata, indent=2))

    print(f"Sweep dir: {sweep_dir}")
    print(f"Model: {model_dir} ({model_path / 'vllm-config.yaml'})")
    print(f"Running baseline ({args.benchmark})...")

    vllm_config = str(model_path / "vllm-config.yaml")
    harness = PROJECT_ROOT / "scripts" / "benchmark_harness.py"
    env = os.environ.copy()
    env["VLLM_CONFIG"] = vllm_config
    cmd = [
        sys.executable,
        str(harness),
        "--start-llm",
        "--benchmark", args.benchmark,
        "--description", "baseline",
        "--run-dir", str(baseline_dir),
    ]
    if args.data:
        cmd.extend(["--data", args.data])
    if args.max_requests:
        cmd.extend(["--max-requests", str(args.max_requests)])
    if args.max_seconds:
        cmd.extend(["--max-seconds", str(args.max_seconds)])

    baseline_runllm = baseline_dir / "runllm"
    if not baseline_runllm.exists():
        shutil.copytree(model_path, baseline_runllm, ignore=shutil.ignore_patterns(".git"))

    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    if r.returncode != 0:
        print("Baseline run failed")
        return r.returncode

    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.sweep_utils import update_best_runllm
    update_best_runllm(sweep_dir, model_path)
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "ai_experiment.py"), "--refresh-leaderboard", "--sweep", name],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    print(f"Baseline saved to {baseline_dir}")
    print(f"Run 'make improve SWEEP={name}' to try LLM-suggested improvements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
