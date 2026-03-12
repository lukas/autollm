#!/usr/bin/env python3
"""
Fast test (<5s): verify runllm apply runs delete-pod first.
No kubectl, no network - just checks Makefile structure and dry-run order.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNLLM = PROJECT_ROOT / "runllm"


def main() -> int:
    makefile = RUNLLM / "Makefile"
    if not makefile.exists():
        print("runllm/Makefile not found")
        return 1

    # 1. Check Makefile has apply: delete-pod
    text = makefile.read_text()
    if not re.search(r"apply:\s*delete-pod", text):
        print("FAIL: runllm Makefile apply target must depend on delete-pod")
        return 1

    if "delete-pod:" not in text:
        print("FAIL: runllm Makefile missing delete-pod target")
        return 1

    # 2. Dry-run apply - verify delete runs before kubectl apply
    r = subprocess.run(
        ["make", "-n", "apply"],
        cwd=str(RUNLLM),
        capture_output=True,
        text=True,
        timeout=5,
    )
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("make")]

    delete_idx = next((i for i, l in enumerate(lines) if "delete" in l and "kubectl" in l), None)
    apply_idx = next((i for i, l in enumerate(lines) if "apply" in l and "kubectl" in l), None)

    if delete_idx is None:
        print("FAIL: dry-run did not show kubectl delete")
        return 1
    if apply_idx is None:
        print("FAIL: dry-run did not show kubectl apply")
        return 1
    if delete_idx >= apply_idx:
        print("FAIL: delete must run before apply in make apply")
        return 1

    print("OK: runllm apply runs delete-pod before kubectl apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
