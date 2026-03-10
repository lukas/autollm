#!/usr/bin/env python3
"""Clear stuck AI optimizer state so dashboard shows Start button."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "results" / "ai_optimizer_state.json"


def main() -> None:
    if not STATE_FILE.exists():
        print("No state file — already clean.")
        return
    try:
        state = json.loads(STATE_FILE.read_text())
        if state.get("current_run") is None:
            print("State already clean.")
            return
        state["current_run"] = None
        STATE_FILE.write_text(json.dumps(state, indent=2))
        print("Cleared stuck state. Dashboard will show Start.")
    except Exception as e:
        print(f"Could not clear state: {e}")


if __name__ == "__main__":
    main()
