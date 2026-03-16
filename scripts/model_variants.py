#!/usr/bin/env python3
"""Helpers for sweep-compatible model families and backend variants under runllm/."""
from __future__ import annotations

from pathlib import Path

BACKEND_SUFFIXES: dict[str, str] = {
    "-vllm": "vllm",
    "-sglang": "sglang",
}


def canonical_model_family(model_name: str) -> str:
    """Normalize a concrete variant or family name to its shared family name."""
    for suffix in BACKEND_SUFFIXES:
        if model_name.endswith(suffix):
            return model_name[: -len(suffix)]
    return model_name


def backend_from_model_dir(model_name: str) -> str:
    """Infer backend from a model family or concrete variant naming convention."""
    for suffix, backend in BACKEND_SUFFIXES.items():
        if model_name.endswith(suffix):
            return backend
    return "vllm"


def _variant_candidates(family: str) -> list[str]:
    return [family + "-vllm", family, *(family + suffix for suffix in BACKEND_SUFFIXES if suffix != "-vllm")]


def list_model_variants(runllm_root: Path, model_name: str) -> list[str]:
    """List available sweep-compatible backend variants for a model family."""
    family = canonical_model_family(model_name)
    candidates = _variant_candidates(family)
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        variant_dir = runllm_root / candidate
        if variant_dir.is_dir() and (variant_dir / "vllm-config.yaml").exists():
            variants.append(candidate)
            seen.add(candidate)
    return variants


def list_model_families(runllm_root: Path) -> list[str]:
    """List canonical model families available under runllm/."""
    families: set[str] = set()
    if not runllm_root.exists():
        return []
    for entry in runllm_root.iterdir():
        if entry.is_dir() and (entry / "vllm-config.yaml").exists():
            families.add(canonical_model_family(entry.name))
    return sorted(families)


def default_variant_for_family(runllm_root: Path, model_name: str) -> str:
    """Pick the default concrete variant to use as the baseline for a family."""
    variants = list_model_variants(runllm_root, model_name)
    return variants[0] if variants else canonical_model_family(model_name)


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
