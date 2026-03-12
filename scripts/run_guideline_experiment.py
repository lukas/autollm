#!/usr/bin/env python3
"""
Run Guideline benchmark with progress tracking for experiment mode.
Writes query_progress.json with queries_completed; output is streamed to run_dir.
Used by ai_experiment.py when EXPERIMENT_RUN_DIR is set.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BENCHMARK_PRESETS = {
    "quick": ("synchronous", "5", "30", "prompt_tokens=64,output_tokens=64"),
    "sync": ("synchronous", "20", "60", "prompt_tokens=64,output_tokens=64"),
    "sweep": ("sweep", None, "60", "prompt_tokens=256,output_tokens=128"),
    "medium": ("synchronous", "200", "300", "prompt_tokens=256,output_tokens=128"),
    "long": ("synchronous", "1000", "600", "prompt_tokens=256,output_tokens=128"),
}

# Patterns to extract completed request count from guidellm progress output.
# Must be specific to avoid matching config dump lines (e.g. max_seconds: 300).
COMPLETED_PATTERNS = [
    r"(?:successful|processed)_requests['\"]?\s*[:=]\s*(\d+)",
    r"\b(\d+)/\d+\s*(?:requests?|completed)",
    r"(?:^|\s)Comp\s+(\d+)(?:\s|$)",
    r"processed_requests\D+(\d+)",
]



def _parse_completed_count(line: str) -> int | None:
    for pat in COMPLETED_PATTERNS:
        m = re.search(pat, line, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                pass
    return None


def main() -> int:
    run_dir = Path(os.environ["EXPERIMENT_RUN_DIR"])
    benchmark = os.environ.get("EXPERIMENT_BENCHMARK", "quick")
    description = os.environ.get("EXPERIMENT_DESCRIPTION", "ai_experiment")
    run_dir.mkdir(parents=True, exist_ok=True)

    preset = BENCHMARK_PRESETS.get(benchmark, BENCHMARK_PRESETS["quick"])
    cfg = {
        "profile": preset[0],
        "max_requests": preset[1],
        "max_seconds": preset[2],
        "data": preset[3],
    }

    cmd = [
        "uv", "run", "guidellm", "benchmark",
        "--target", os.environ.get("EXPERIMENT_TARGET", "http://localhost:8000"),
        "--backend-args", '{"http2":false}',
        "--profile", cfg["profile"],
        "--request-type", "chat_completions",
        "--max-seconds", cfg["max_seconds"],
        "--data", cfg["data"],
        "--output-dir", str(run_dir),
        "--outputs", "json",
        "--outputs", "csv",
    ]
    if cfg["max_requests"]:
        cmd.extend(["--max-requests", cfg["max_requests"]])
    # No --disable-progress so we get progress output to parse

    progress_file = run_dir / "query_progress.json"
    harness_log = run_dir / "harness_output.txt"

    def write_progress(queries: int) -> None:
        progress_file.write_text(json.dumps({
            "queries_completed": queries,
            "last_updated": datetime.now().isoformat(),
        }, indent=2))

    write_progress(0)

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    max_completed = 0
    with open(harness_log, "w", encoding="utf-8") as logf:
        try:
            if proc.stdout:
                for line in proc.stdout:
                    logf.write(line)
                    logf.flush()
                    n = _parse_completed_count(line)
                    if n is not None and n > max_completed:
                        max_completed = n
                        write_progress(max_completed)
        except Exception:
            pass
    proc.wait()

    write_progress(max_completed)

    if proc.returncode == 0 and (run_dir / "benchmark.json").exists() and not (run_dir / "benchmarks.json").exists():
        import shutil
        shutil.copy(run_dir / "benchmark.json", run_dir / "benchmarks.json")

    return proc.returncode

if __name__ == "__main__":
    sys.exit(main())
