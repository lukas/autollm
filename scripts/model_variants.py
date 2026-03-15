#!/usr/bin/env python3
"""Helpers for sweep-compatible backend variants under runllm/."""
from __future__ import annotations

from pathlib import Path

BACKEND_SUFFIXES: dict[str, str] = {
    "-sglang": "sglang",
}


def canonical_model_family(model_dir: str) -> str:
    """Normalize a model dir to its shared family name."""
    for suffix in BACKEND_SUFFIXES:
        if model_dir.endswith(suffix):
            return model_dir[: -len(suffix)]
    return model_dir


def backend_from_model_dir(model_dir: str) -> str:
    """Infer backend from a model dir naming convention."""
    for suffix, backend in BACKEND_SUFFIXES.items():
        if model_dir.endswith(suffix):
            return backend
    return "vllm"


def list_model_variants(runllm_root: Path, model_dir: str) -> list[str]:
    """List available sweep-compatible backend variants for a model family."""
    family = canonical_model_family(model_dir)
    candidates = [family, *(family + suffix for suffix in BACKEND_SUFFIXES)]
    variants: list[str] = []
    for candidate in candidates:
        variant_dir = runllm_root / candidate
        if variant_dir.is_dir() and (variant_dir / "vllm-config.yaml").exists():
            variants.append(candidate)
    return variants


def infer_backend(config_text: str, makefile_text: str = "") -> str:
    """Infer backend from config or Makefile contents."""
    haystack = f"{config_text}\n{makefile_text}".lower()
    if "sglang" in haystack:
        return "sglang"
    return "vllm"


def infer_backend_from_runllm_dir(runllm_dir: Path) -> str:
    """Infer backend from a runllm directory snapshot."""
    config_text = ""
    makefile_text = ""
    cfg_path = runllm_dir / "vllm-config.yaml"
    if cfg_path.exists():
        config_text = cfg_path.read_text()
    makefile_path = runllm_dir / "Makefile"
    if makefile_path.exists():
        makefile_text = makefile_path.read_text()
    return infer_backend(config_text, makefile_text)
