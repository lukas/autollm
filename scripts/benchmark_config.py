#!/usr/bin/env python3
"""
Shared benchmark presets and Guideline progress parsing helpers.
"""
from __future__ import annotations

import re

BENCHMARK_PRESETS: dict[str, dict[str, str | None]] = {
    "quick": {
        "profile": "synchronous",
        "max_requests": "5",
        "max_seconds": "30",
        "data": "prompt_tokens=64,output_tokens=64",
    },
    "sync": {
        "profile": "synchronous",
        "max_requests": "20",
        "max_seconds": "60",
        "data": "prompt_tokens=64,output_tokens=64",
    },
    "sweep": {
        "profile": "sweep",
        "max_requests": None,
        "max_seconds": "60",
        "data": "prompt_tokens=256,output_tokens=128",
    },
    "medium": {
        "profile": "synchronous",
        "max_requests": "200",
        "max_seconds": "300",
        "data": "prompt_tokens=256,output_tokens=128",
    },
    "long": {
        "profile": "synchronous",
        "max_requests": "1000",
        "max_seconds": "600",
        "data": "prompt_tokens=256,output_tokens=128",
    },
}

BENCHMARK_MAX_REQUESTS = {
    name: int(preset["max_requests"]) if preset["max_requests"] else 0
    for name, preset in BENCHMARK_PRESETS.items()
}

COMPLETED_PATTERNS = [
    r"(?:successful|processed)_requests['\"]?\s*[:=]\s*(\d+)",
    r"\b(\d+)/\d+\s*(?:requests?|completed)",
    r"(?:^|\s)Comp\s+(\d+)(?:\s|$)",
    r"processed_requests\D+(\d+)",
]


def parse_completed_count(line: str) -> int | None:
    for pat in COMPLETED_PATTERNS:
        m = re.search(pat, line, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                pass
    return None
