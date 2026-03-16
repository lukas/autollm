#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark_config import BENCHMARK_PRESETS

RUN_DIR_RE = re.compile(r"^\d{8}_\d{6}$")
SWEEP_STOP_EXIT_CODE = 40
MAX_CONSECUTIVE_FAILED_RUNS = int(os.environ.get("SWEEP_MAX_CONSECUTIVE_FAILURES", "10"))
MAX_CONSECUTIVE_UNFIXABLE_RUNS = int(os.environ.get("SWEEP_MAX_CONSECUTIVE_UNFIXABLE_FAILURES", "2"))

UNFIXABLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("credits", re.compile(r"insufficient[_ -]?quota|quota exceeded|out of credits?|credit balance|billing|payment required", re.I)),
    ("auth", re.compile(r"unauthorized|authentication failed|invalid api key|api key.*missing|forbidden|permission denied", re.I)),
    ("exa", re.compile(r"\bexa\b.*(quota|credits?|billing|payment|required|401|403|429)", re.I)),
    ("timeout", re.compile(r"timed out|timeout|deadline exceeded|read timeout|connect timeout|gateway timeout|504", re.I)),
]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def effective_agent_model(provider: str, configured_model: str = "") -> str:
    provider = (provider or "anthropic").lower()
    if configured_model:
        return configured_model
    if provider == "openai":
        return "gpt-5.4"
    return "claude-opus-4-6"


def classify_failure_text(text: str) -> dict[str, Any]:
    message = (text or "").strip()
    lowered = message.lower()
    for category, pattern in UNFIXABLE_PATTERNS:
        match = pattern.search(message)
        if match:
            return {
                "is_unfixable": True,
                "category": category,
                "matched_text": match.group(0),
                "summary": match.group(0),
            }
    return {
        "is_unfixable": False,
        "category": "fixable",
        "matched_text": "",
        "summary": lowered[:120],
    }


def iter_sweep_run_dirs(sweep_dir: Path) -> list[Path]:
    if not sweep_dir.exists():
        return []
    return sorted(
        [d for d in sweep_dir.iterdir() if d.is_dir() and RUN_DIR_RE.match(d.name)],
        key=lambda d: d.name,
    )


def get_run_status(run_dir: Path) -> dict[str, Any]:
    meta = _load_json(run_dir / "run_metadata.json")
    if "success" in meta:
        success = bool(meta.get("success"))
    else:
        success = (run_dir / "benchmarks.json").exists()
    result = str(meta.get("result", "") or "")
    classification = meta.get("failure_classification")
    if not success and not classification:
        classification = classify_failure_text(result)
    elif success and not classification:
        classification = {"is_unfixable": False, "category": "success", "matched_text": "", "summary": ""}
    return {
        "name": run_dir.name,
        "success": success,
        "result": result,
        "failure_classification": classification or {"is_unfixable": False, "category": "unknown"},
        "description": str(meta.get("description", "") or ""),
        "backend": str(meta.get("backend", "") or ""),
        "agent_provider": str(meta.get("agent_provider", "") or ""),
        "agent_model": str(meta.get("agent_model", "") or ""),
    }


def get_failure_streak_status(sweep_dir: Path) -> dict[str, Any]:
    failure_streak = 0
    unfixable_streak = 0
    recent_failures: list[dict[str, Any]] = []
    for run_dir in reversed(iter_sweep_run_dirs(sweep_dir)):
        status = get_run_status(run_dir)
        if status["success"]:
            break
        failure_streak += 1
        recent_failures.append(status)
        if status["failure_classification"].get("is_unfixable"):
            unfixable_streak += 1
        else:
            break
    return {
        "failure_streak": failure_streak,
        "unfixable_streak": unfixable_streak,
        "recent_failures": recent_failures,
    }


def should_stop_sweep(sweep_dir: Path) -> dict[str, Any]:
    status = get_failure_streak_status(sweep_dir)
    failure_streak = status["failure_streak"]
    unfixable_streak = status["unfixable_streak"]
    if unfixable_streak >= MAX_CONSECUTIVE_UNFIXABLE_RUNS:
        latest = status["recent_failures"][:MAX_CONSECUTIVE_UNFIXABLE_RUNS]
        summary = "; ".join(
            f"{run['name']}: {run['failure_classification'].get('category', 'unfixable')} ({run['result'][:120]})"
            for run in latest
        )
        return {
            "stop": True,
            "reason": (
                f"Stopping sweep after {unfixable_streak} consecutive unfixable failures "
                f"(threshold {MAX_CONSECUTIVE_UNFIXABLE_RUNS}). {summary}"
            ),
            **status,
        }
    if failure_streak >= MAX_CONSECUTIVE_FAILED_RUNS:
        latest = status["recent_failures"][:3]
        summary = "; ".join(f"{run['name']}: {run['result'][:120]}" for run in latest)
        return {
            "stop": True,
            "reason": (
                f"Stopping sweep after {failure_streak} consecutive failed runs "
                f"(threshold {MAX_CONSECUTIVE_FAILED_RUNS}). Latest failures: {summary}"
            ),
            **status,
        }
    return {"stop": False, "reason": "", **status}


def _best_runllm_target(sweep_dir: Path) -> str:
    best_link = sweep_dir / "best-runllm"
    if not best_link.exists():
        return ""
    try:
        return str(best_link.resolve().relative_to(sweep_dir.parent.parent))
    except Exception:
        try:
            return str(best_link.resolve())
        except Exception:
            return ""


def _benchmark_details(metadata: dict[str, Any]) -> dict[str, Any]:
    benchmark = str(metadata.get("benchmark", "") or "")
    preset = BENCHMARK_PRESETS.get(benchmark, {})
    return {
        "benchmark": benchmark or "quick",
        "data": metadata.get("data") or preset.get("data"),
        "max_requests": metadata.get("max_requests") or preset.get("max_requests"),
        "max_seconds": metadata.get("max_seconds") or preset.get("max_seconds"),
        "profile": preset.get("profile", ""),
    }


def write_sweep_overview(
    sweep_dir: Path,
    *,
    agent_provider: str | None = None,
    agent_model: str | None = None,
) -> Path:
    metadata = _load_json(sweep_dir / "sweep_metadata.json")
    benchmark = _benchmark_details(metadata)
    run_dirs = iter_sweep_run_dirs(sweep_dir)
    statuses = [get_run_status(run_dir) for run_dir in run_dirs]
    successes = [status for status in statuses if status["success"]]
    failures = [status for status in statuses if not status["success"]]
    latest = statuses[-1] if statuses else None
    stop_status = should_stop_sweep(sweep_dir)

    provider = agent_provider or metadata.get("last_agent_provider") or metadata.get("agent_provider") or "anthropic"
    model = agent_model or metadata.get("last_agent_model") or metadata.get("agent_model") or effective_agent_model(provider)
    runllm_dirs = metadata.get("model_variants") or ([metadata.get("baseline_variant")] if metadata.get("baseline_variant") else [])
    runllm_dirs = [f"runllm/{entry}" for entry in runllm_dirs if entry]

    baseline_complete = (sweep_dir / "baseline" / "benchmarks.json").exists()
    overview_lines = [
        "# Sweep Overview",
        "",
        f"- Sweep: `{metadata.get('name') or sweep_dir.name.replace('sweep-', '', 1)}`",
        f"- Started: `{metadata.get('created_at', 'unknown')}`",
        f"- Last updated: `{datetime.now().isoformat()}`",
        f"- Goal: `{metadata.get('goal') or 'not set'}`",
        f"- Benchmark preset: `{benchmark['benchmark']}`",
        f"- Benchmark profile: `{benchmark['profile'] or 'unknown'}`",
        f"- Dataset / data config: `{benchmark['data']}`",
        f"- Max requests: `{benchmark['max_requests']}`",
        f"- Max seconds: `{benchmark['max_seconds']}`",
        f"- Agent provider: `{provider}`",
        f"- Agent model: `{model}`",
        f"- Model family: `{metadata.get('model_family') or metadata.get('model_dir') or 'unknown'}`",
        f"- Baseline variant: `{('runllm/' + metadata['baseline_variant']) if metadata.get('baseline_variant') else ('runllm/' + metadata['model_dir']) if metadata.get('model_dir') else 'unknown'}`",
        f"- Available runllm dirs: {', '.join(f'`{entry}`' for entry in runllm_dirs) if runllm_dirs else '`unknown`'}",
        f"- Baseline complete: `{baseline_complete}`",
        f"- Improvement runs: `{len(run_dirs)}`",
        f"- Successful runs: `{len(successes)}`",
        f"- Failed runs: `{len(failures)}`",
        f"- Current failure streak: `{stop_status['failure_streak']}`",
        f"- Current unfixable failure streak: `{stop_status['unfixable_streak']}`",
        (
            f"- Latest run: `{latest['name']}` ({'success' if latest['success'] else 'failure'})"
            if latest else "- Latest run: `none`"
        ),
        f"- Best runllm target: `{_best_runllm_target(sweep_dir) or 'not available yet'}`",
        (
            f"- Sweep stop status: `{stop_status['reason']}`"
            if stop_status["stop"]
            else f"- Sweep stop policy: stop after `{MAX_CONSECUTIVE_FAILED_RUNS}` failed runs in a row or `{MAX_CONSECUTIVE_UNFIXABLE_RUNS}` unfixable failures in a row"
        ),
    ]

    if latest and not latest["success"] and latest["result"]:
        overview_lines.extend([
            "",
            "## Latest Failure",
            "",
            f"- Result: `{latest['result'][:400]}`",
            f"- Classification: `{latest['failure_classification'].get('category', 'unknown')}`",
        ])

    path = sweep_dir / "OVERVIEW.md"
    path.write_text("\n".join(overview_lines) + "\n")
    return path
