#!/usr/bin/env python3
"""
Inspect experiment progress. Run while 'make experiment' is running.
After 3 min, if the experiment appears stuck, use --kill to terminate it.

Usage:
  python scripts/experiment_inspect.py
  python scripts/experiment_inspect.py --kill
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRESS_FILE = PROJECT_ROOT / "results" / "experiment_progress.json"
INSPECT_AFTER_SEC = int(os.environ.get("EXPERIMENT_INSPECT_AFTER_SEC", "180"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect experiment progress")
    parser.add_argument("--kill", action="store_true", help="Kill experiment if stuck past inspect timeout")
    args = parser.parse_args()

    if not PROGRESS_FILE.exists():
        print("No experiment in progress (no progress file)")
        return 0

    try:
        data = json.loads(PROGRESS_FILE.read_text())
    except Exception as e:
        print(f"Could not read progress: {e}")
        return 1

    phase = data.get("phase", "?")
    started = data.get("phase_started", "")
    pid = data.get("pid")

    # Compute elapsed for this phase (approximate)
    elapsed_sec = 0
    if started:
        try:
            # Strip timezone for simple local elapsed
            s = started.replace("Z", "")[:26]
            dt = datetime.fromisoformat(s)
            elapsed_sec = (datetime.now() - dt).total_seconds()
        except Exception:
            pass

    print(f"Phase: {phase}")
    print(f"Phase started: {started}")
    print(f"PID: {pid}")
    if elapsed_sec > 0:
        print(f"Elapsed (approx): {int(elapsed_sec)}s")
    if "reason" in data:
        print(f"Reason: {data['reason']}")
    print()

    if args.kill and pid and phase not in ("done", "aborted"):
        if elapsed_sec >= INSPECT_AFTER_SEC:
            print(f"Killing experiment (stuck {int(elapsed_sec)}s >= {INSPECT_AFTER_SEC}s)")
            try:
                os.kill(pid, signal.SIGTERM)
                print("Sent SIGTERM")
            except ProcessLookupError:
                print("Process already exited")
            except PermissionError:
                print("Permission denied (need same user?)")
                return 1
        else:
            print(f"Not killing: elapsed {int(elapsed_sec)}s < {INSPECT_AFTER_SEC}s. Run again after {INSPECT_AFTER_SEC - int(elapsed_sec)}s")
    elif args.kill:
        print("Nothing to kill (phase is done or aborted)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
