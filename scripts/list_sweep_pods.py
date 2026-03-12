#!/usr/bin/env python3
"""
List running Kubernetes pods associated with an autollm sweep.

Usage:
  python scripts/list_sweep_pods.py --sweep qwen-throughput
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys


def _k8s_label_value(value: str) -> str:
    value = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower())
    value = value.strip("-.")
    return value[:63] or "default"


def main() -> int:
    parser = argparse.ArgumentParser(description="List running pods for a sweep")
    parser.add_argument("--sweep", "-s", required=True, help="Sweep name (e.g. qwen-throughput)")
    args = parser.parse_args()

    sweep = _k8s_label_value(args.sweep)
    selector = f"autollm-managed=true,autollm-sweep={sweep}"
    cmd = [
        "kubectl",
        "get",
        "pods",
        "-l",
        selector,
        "-o",
        "wide",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or r.stdout or "kubectl get pods failed").strip() + "\n")
        return r.returncode

    output = (r.stdout or "").strip()
    if output:
        print(output)
    else:
        print(f"No pods found for sweep '{args.sweep}'.")
        print("Note: only pods created after sweep-label support was added will appear here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
