#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROFILE_METRICS = (
    "vllm:num_preemptions_total",
    "vllm:gpu_cache_usage_perc",
    "vllm:cpu_cache_usage_perc",
    "vllm:num_requests_waiting",
    "vllm:num_requests_running",
    "vllm:avg_prompt_throughput_toks_per_s",
    "vllm:avg_generation_throughput_toks_per_s",
    "vllm:time_to_first_token_seconds_sum",
    "vllm:time_to_first_token_seconds_count",
    "vllm:e2e_request_latency_seconds_sum",
    "vllm:e2e_request_latency_seconds_count",
)

GPU_QUERY_FIELDS = (
    "index",
    "name",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
)


def _safe_float(value: str) -> float | None:
    try:
        value = value.strip()
        if not value or value in {"[Not Supported]", "N/A"}:
            return None
        return float(value)
    except Exception:
        return None


def parse_vllm_metrics(raw: str, keys: tuple[str, ...] = PROFILE_METRICS) -> dict[str, float]:
    """Extract the first scalar value for each vLLM Prometheus metric we care about."""
    summary: dict[str, float] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        metric_name, value_str = parts
        base_name = metric_name.split("{", 1)[0]
        if base_name not in keys or base_name in summary:
            continue
        value = _safe_float(value_str)
        if value is not None:
            summary[base_name] = value
    return summary


def scrape_vllm_metrics(
    pod_name: str,
    env: dict[str, str],
    *,
    request_timeout: int = 5,
    subprocess_timeout: int = 15,
) -> tuple[str, dict[str, float]] | None:
    try:
        r = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "curl",
                "-sf",
                "--max-time",
                str(request_timeout),
                "http://localhost:8000/metrics",
            ],
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
            env=env,
        )
        if r.returncode != 0 or not r.stdout:
            return None
        return r.stdout, parse_vllm_metrics(r.stdout)
    except Exception:
        return None


def _yaml_resources(yaml_path: Path) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    if not yaml_path.exists():
        return resources
    try:
        doc = yaml.safe_load(yaml_path.read_text()) or {}
        container = ((doc.get("spec") or {}).get("containers") or [{}])[0]
        resources = container.get("resources") or {}
    except Exception:
        return {}
    return resources if isinstance(resources, dict) else {}


def collect_hardware_context(
    pod_name: str,
    yaml_path: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    resources = _yaml_resources(yaml_path)
    context: dict[str, Any] = {
        "captured_at": datetime.now().isoformat(),
        "pod_name": pod_name,
        "gpu_count": ((resources.get("limits") or {}).get("nvidia.com/gpu")),
        "resources": resources,
    }
    try:
        r = subprocess.run(
            ["kubectl", "get", "pod", pod_name, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        if r.returncode == 0 and r.stdout:
            pod = json.loads(r.stdout)
            spec = pod.get("spec") or {}
            status = pod.get("status") or {}
            context.update(
                {
                    "namespace": pod.get("metadata", {}).get("namespace"),
                    "node_name": spec.get("nodeName"),
                    "pod_ip": status.get("podIP"),
                    "host_ip": status.get("hostIP"),
                    "phase": status.get("phase"),
                    "start_time": status.get("startTime"),
                }
            )
    except Exception:
        pass
    return context


def write_hardware_context(run_dir: Path, context: dict[str, Any]) -> None:
    (run_dir / "hardware_context.json").write_text(json.dumps(context, indent=2) + "\n")


def write_vllm_snapshot(
    pod_name: str,
    run_dir: Path,
    env: dict[str, str],
    *,
    raw_filename: str = "vllm_metrics.txt",
    summary_filename: str = "vllm_metrics_summary.json",
) -> None:
    scraped = scrape_vllm_metrics(pod_name, env)
    if not scraped:
        return
    raw, summary = scraped
    (run_dir / raw_filename).write_text(raw)
    if summary:
        (run_dir / summary_filename).write_text(json.dumps(summary, indent=2) + "\n")


def _sample_gpu_metrics(pod_name: str, env: dict[str, str]) -> list[dict[str, Any]] | None:
    query = ",".join(GPU_QUERY_FIELDS)
    cmd = [
        "kubectl",
        "exec",
        pod_name,
        "--",
        "sh",
        "-lc",
        (
            "command -v nvidia-smi >/dev/null 2>&1 || exit 127; "
            f"nvidia-smi --query-gpu={query} --format=csv,noheader,nounits"
        ),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    rows: list[dict[str, Any]] = []
    for line in r.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(GPU_QUERY_FIELDS):
            continue
        row: dict[str, Any] = {
            "index": parts[0],
            "name": parts[1],
            "gpu_utilization_pct": _safe_float(parts[2]),
            "memory_utilization_pct": _safe_float(parts[3]),
            "memory_used_mb": _safe_float(parts[4]),
            "memory_total_mb": _safe_float(parts[5]),
            "temperature_c": _safe_float(parts[6]),
            "power_draw_w": _safe_float(parts[7]),
        }
        rows.append(row)
    return rows or None


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
        f.flush()


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _max(values: list[float]) -> float | None:
    return max(values) if values else None


def _extract_metric_series(samples: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for sample in samples:
        metrics = sample.get("metrics") or {}
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def _gpu_series(samples: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        for gpu in sample.get("gpus") or []:
            value = gpu.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
    return values


def summarize_profile(
    metric_samples: list[dict[str, Any]],
    gpu_samples: list[dict[str, Any]],
    hardware_context: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    preemptions = _extract_metric_series(metric_samples, "vllm:num_preemptions_total")
    gpu_cache = _extract_metric_series(metric_samples, "vllm:gpu_cache_usage_perc")
    cpu_cache = _extract_metric_series(metric_samples, "vllm:cpu_cache_usage_perc")
    waiting = _extract_metric_series(metric_samples, "vllm:num_requests_waiting")
    running = _extract_metric_series(metric_samples, "vllm:num_requests_running")
    prompt_tps = _extract_metric_series(metric_samples, "vllm:avg_prompt_throughput_toks_per_s")
    gen_tps = _extract_metric_series(metric_samples, "vllm:avg_generation_throughput_toks_per_s")
    gpu_util = _gpu_series(gpu_samples, "gpu_utilization_pct")
    gpu_mem_util = _gpu_series(gpu_samples, "memory_utilization_pct")
    gpu_mem_used = _gpu_series(gpu_samples, "memory_used_mb")
    power_draw = _gpu_series(gpu_samples, "power_draw_w")

    hints: list[str] = []
    if gpu_cache and _max(gpu_cache) and _max(gpu_cache) >= 0.9:
        hints.append("kv_cache_pressure_high")
    if waiting and _mean(waiting) and _mean(waiting) >= 1 and (not gen_tps or (_mean(gen_tps) or 0) < 50):
        hints.append("queueing_high_with_low_generation_throughput")
    if preemptions and preemptions[-1] > preemptions[0]:
        hints.append("preemptions_increased_during_run")
    if gpu_util and (_mean(gpu_util) or 0) < 40 and prompt_tps and (_mean(prompt_tps) or 0) < 200:
        hints.append("gpu_underutilized_possible_cpu_or_batching_limit")

    return {
        "captured_at": datetime.now().isoformat(),
        "sample_count": len(metric_samples),
        "gpu_sample_count": len(gpu_samples),
        "hardware_context": hardware_context,
        "profiling_errors": errors,
        "nvidia_smi_available": bool(gpu_samples),
        "summary": {
            "preemptions_start": preemptions[0] if preemptions else None,
            "preemptions_end": preemptions[-1] if preemptions else None,
            "preemptions_delta": (preemptions[-1] - preemptions[0]) if len(preemptions) >= 2 else None,
            "gpu_cache_mean": _mean(gpu_cache),
            "gpu_cache_peak": _max(gpu_cache),
            "cpu_cache_mean": _mean(cpu_cache),
            "cpu_cache_peak": _max(cpu_cache),
            "waiting_mean": _mean(waiting),
            "waiting_peak": _max(waiting),
            "running_mean": _mean(running),
            "running_peak": _max(running),
            "prompt_throughput_mean": _mean(prompt_tps),
            "prompt_throughput_peak": _max(prompt_tps),
            "generation_throughput_mean": _mean(gen_tps),
            "generation_throughput_peak": _max(gen_tps),
            "gpu_utilization_mean": _mean(gpu_util),
            "gpu_utilization_peak": _max(gpu_util),
            "gpu_memory_utilization_mean": _mean(gpu_mem_util),
            "gpu_memory_utilization_peak": _max(gpu_mem_util),
            "gpu_memory_used_mb_peak": _max(gpu_mem_used),
            "gpu_power_draw_w_peak": _max(power_draw),
        },
        "diagnosis_hints": hints,
    }


class VLLMProfiler:
    """Best-effort background sampler for vLLM and GPU telemetry."""

    def __init__(
        self,
        *,
        pod_name: str,
        run_dir: Path,
        env: dict[str, str],
        yaml_path: Path,
        interval_sec: float = 5.0,
        log_fn=None,
    ) -> None:
        self.pod_name = pod_name
        self.run_dir = run_dir
        self.env = env
        self.yaml_path = yaml_path
        self.interval_sec = interval_sec
        self.log_fn = log_fn
        self.metric_path = run_dir / "vllm_metrics_timeseries.jsonl"
        self.gpu_path = run_dir / "gpu_metrics_timeseries.jsonl"
        self.profile_path = run_dir / "vllm_metrics_profile.json"
        self._metric_samples: list[dict[str, Any]] = []
        self._gpu_samples: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = time.time()
        self.hardware_context = collect_hardware_context(pod_name, yaml_path, env)
        write_hardware_context(run_dir, self.hardware_context)

    def _log(self, message: str) -> None:
        if self.log_fn:
            try:
                self.log_fn(message)
            except Exception:
                pass

    def _sample_once(self) -> None:
        elapsed = round(time.time() - self._started, 3)
        ts = datetime.now().isoformat()
        scraped = scrape_vllm_metrics(self.pod_name, self.env)
        if scraped:
            _, metrics = scraped
            payload = {"ts": ts, "elapsed_sec": elapsed, "metrics": metrics}
            self._metric_samples.append(payload)
            _append_jsonl(self.metric_path, payload)
        else:
            self._errors.append(f"{ts}: failed to scrape /metrics")
        gpus = _sample_gpu_metrics(self.pod_name, self.env)
        if gpus:
            payload = {"ts": ts, "elapsed_sec": elapsed, "gpus": gpus}
            self._gpu_samples.append(payload)
            _append_jsonl(self.gpu_path, payload)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._sample_once()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log(f"Started vLLM profiler (interval={self.interval_sec:.1f}s)")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self._sample_once()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_sec + 1.0))
        profile = summarize_profile(
            self._metric_samples,
            self._gpu_samples,
            self.hardware_context,
            self._errors,
        )
        self.profile_path.write_text(json.dumps(profile, indent=2) + "\n")
        self._log(
            "Stopped vLLM profiler "
            f"(metric_samples={len(self._metric_samples)}, gpu_samples={len(self._gpu_samples)})"
        )
