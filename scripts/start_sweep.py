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
from model_variants import (
    backend_from_model_dir,
    canonical_model_family,
    default_variant_for_family,
    list_model_families,
    list_model_variants,
)
from sweep_state import effective_agent_model, write_sweep_overview

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNLLM_ROOT = PROJECT_ROOT / "runllm"
DEFAULT_MODEL = "qwen2.5-1.5b"


def _list_models() -> list[str]:
    """List available model families under runllm/."""
    return list_model_families(RUNLLM_ROOT)


def _resolve_model_variants(runllm_root: Path, model_family: str, requested_variants: str | None = None) -> list[str]:
    """Resolve the variant set tracked by the sweep."""
    if not requested_variants:
        return list_model_variants(runllm_root, model_family)

    seen: set[str] = set()
    variants: list[str] = []
    for raw in requested_variants.split(","):
        candidate = raw.strip()
        if not candidate or candidate in seen:
            continue
        variant_dir = runllm_root / candidate
        if not variant_dir.is_dir() or not (variant_dir / "vllm-config.yaml").exists():
            raise ValueError(f"Model variant '{candidate}' not found under runllm/")
        variants.append(candidate)
        seen.add(candidate)

    return variants


def _resolve_baseline_variant(
    runllm_root: Path,
    model_name: str,
    model_variants: list[str],
    baseline_variant: str | None = None,
) -> str:
    """Resolve which concrete variant should be used for the baseline run."""
    if baseline_variant:
        variant = baseline_variant.strip()
        variant_dir = runllm_root / variant
        if not variant_dir.is_dir() or not (variant_dir / "vllm-config.yaml").exists():
            raise ValueError(f"Baseline variant '{variant}' not found under runllm/")
        return variant

    explicit_variant = model_name.strip()
    variant_dir = runllm_root / explicit_variant
    if variant_dir.is_dir() and (variant_dir / "vllm-config.yaml").exists():
        return explicit_variant

    if model_variants:
        return default_variant_for_family(runllm_root, model_name)
    return explicit_variant


def _allow_backend_switches(model_variants: list[str]) -> bool:
    """Decide whether improve runs may switch across backend templates."""
    return len({backend_from_model_dir(variant) for variant in model_variants}) > 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Start a new sweep and run baseline")
    parser.add_argument("--sweep", "-s", required=True, help="Sweep name (e.g. qwen-1b-latency)")
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Model family under runllm/ (available: {', '.join(_list_models()) or '?'})",
    )
    parser.add_argument("--model-dir", help=argparse.SUPPRESS)
    parser.add_argument(
        "--baseline-variant",
        help="Concrete runllm variant to use for the baseline run, e.g. 'kimi-sglang'",
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
    parser.add_argument(
        "--model-variants",
        help="Comma-separated runllm variants allowed in this sweep, e.g. 'kimi-vllm,kimi-sglang'",
    )
    args = parser.parse_args()

    name = args.sweep.strip().lower().replace(" ", "-")
    if not name:
        print("Sweep name required. Usage: make sweep SWEEP=my-sweep")
        return 1

    model_name = (args.model_dir or args.model).strip()
    model_family = canonical_model_family(model_name)

    sweep_dir = PROJECT_ROOT / "results" / f"sweep-{name}"
    baseline_dir = sweep_dir / "baseline"
    baseline_complete = baseline_dir.exists() and (baseline_dir / "benchmarks.json").exists()
    if baseline_complete and not args.force:
        print(f"Sweep '{name}' has a complete baseline. Use 'make improve SWEEP={name}' or add --force to re-run baseline.")
        return 1

    sweep_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)

    try:
        model_variants = _resolve_model_variants(RUNLLM_ROOT, model_family, args.model_variants)
        baseline_variant = _resolve_baseline_variant(RUNLLM_ROOT, model_name, model_variants, args.baseline_variant)
    except ValueError as exc:
        print(str(exc))
        return 1
    model_path = RUNLLM_ROOT / baseline_variant
    if not model_variants or not (model_path / "vllm-config.yaml").exists():
        avail = _list_models()
        print(f"Model '{model_name}' not found. Available families: {', '.join(avail)}")
        return 1
    allow_backend_switches = _allow_backend_switches(model_variants)
    agent_provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    agent_model = effective_agent_model(agent_provider, os.environ.get("AI_MODEL", ""))
    sweep_metadata = {
        "name": name,
        "model_family": model_family,
        "baseline_variant": baseline_variant,
        "model_variants": model_variants,
        "allow_backend_switches": allow_backend_switches,
        "created_at": datetime.now().isoformat(),
        "benchmark": args.benchmark,
        "data": args.data,
        "max_requests": args.max_requests,
        "max_seconds": args.max_seconds,
        "goal": args.goal,
        "agent_provider": agent_provider,
        "agent_model": agent_model,
        "last_agent_provider": agent_provider,
        "last_agent_model": agent_model,
    }
    (sweep_dir / "sweep_metadata.json").write_text(json.dumps(sweep_metadata, indent=2))
    write_sweep_overview(sweep_dir, agent_provider=agent_provider, agent_model=agent_model)

    print(f"Sweep dir: {sweep_dir}")
    print(f"Model family: {model_family}")
    print(f"Baseline variant: {baseline_variant} ({model_path / 'vllm-config.yaml'})")
    if model_variants:
        print(f"Backend variants available to improve runs: {', '.join(model_variants)}")
    if allow_backend_switches and len(model_variants) > 1:
        print("Backend switching is enabled for this sweep.")
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
    write_sweep_overview(sweep_dir, agent_provider=agent_provider, agent_model=agent_model)
    print(f"Baseline saved to {baseline_dir}")
    print(f"Run 'make improve SWEEP={name}' to try LLM-suggested improvements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
