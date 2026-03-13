#!/usr/bin/env python3
"""Run guidellm benchmarks as Kubernetes Jobs against vLLM pods in-cluster.

Instead of running guidellm locally (broken on macOS due to multiprocessing
deadlocks) and relying on flaky kubectl port-forward, this module creates a
lightweight K8s Job that runs guidellm directly against the vLLM pod's
cluster IP.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import yaml

from benchmark_config import parse_completed_count

BENCH_IMAGE = os.environ.get("GUIDELLM_BENCH_IMAGE", "python:3.12-slim")
NODE_POOL = "lukas-4h200-pool"
_PIP_INSTALL = "pip install -q 'guidellm[recommended]>=0.5.3' && "
_RESULTS_MARKER_START = "===BENCHMARKS_JSON_START==="
_RESULTS_MARKER_END = "===BENCHMARKS_JSON_END==="


def get_pod_ip(pod_name: str, env: dict | None = None) -> str:
    """Get the cluster IP of a running K8s pod."""
    r = subprocess.run(
        ["kubectl", "get", "pod", pod_name, "-o", "jsonpath={.status.podIP}"],
        capture_output=True, text=True, timeout=15, env=env or os.environ.copy(),
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Failed to get pod IP for {pod_name}: {r.stderr}")
    return r.stdout.strip()


def _build_job_manifest(
    job_name: str, target_url: str, config: dict,
) -> dict:
    """Build a K8s Job manifest dict for a guidellm benchmark."""
    needs_install = "guidellm" not in BENCH_IMAGE
    install_prefix = _PIP_INSTALL if needs_install else ""

    cmd_parts = [
        f"{install_prefix}mkdir -p /tmp/results",
        "guidellm benchmark"
        f" --target {target_url}"
        ' --backend-args \'{"http2":false}\''
        f" --profile {config['profile']}"
        " --request-type chat_completions"
        f" --max-seconds {config['max_seconds']}"
        f" --data {config['data']}"
        " --output-dir /tmp/results"
        " --outputs benchmarks.json"
        " --outputs benchmarks.csv",
    ]
    extra = ""
    if config.get("max_requests"):
        extra += f" --max-requests {config['max_requests']}"
    if config.get("rate"):
        extra += f" --rate {config['rate']}"
    cmd_parts[-1] += extra

    # After guidellm finishes, dump results to stdout so we can capture from logs
    cmd_parts.append(
        f'echo "{_RESULTS_MARKER_START}"'
        " && cat /tmp/results/benchmarks.json"
        f' && echo "{_RESULTS_MARKER_END}"'
    )
    cmd = " && ".join(cmd_parts)

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 600,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "nodeSelector": {
                        "compute.coreweave.com/node-pool": NODE_POOL,
                    },
                    "containers": [{
                        "name": "bench",
                        "image": BENCH_IMAGE,
                        "command": ["/bin/bash", "-c"],
                        "args": [cmd],
                        "resources": {
                            "requests": {"cpu": "2", "memory": "4Gi"},
                            "limits": {"cpu": "4", "memory": "8Gi"},
                        },
                    }],
                },
            },
        },
    }


def _get_job_pod(job_name: str, env: dict, timeout: int = 120) -> str:
    """Wait for the Job's pod to appear and return its name."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = subprocess.run(
            ["kubectl", "get", "pods", "-l", f"job-name={job_name}",
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        time.sleep(2)
    raise RuntimeError(f"No pod found for job {job_name} after {timeout}s")


def _cleanup_job(job_name: str, env: dict) -> None:
    """Delete a benchmark job and its pods."""
    subprocess.run(
        ["kubectl", "delete", "job", job_name, "--ignore-not-found=true"],
        capture_output=True, timeout=30, env=env,
    )


def run_benchmark_k8s(
    *,
    pod_name: str,
    config: dict,
    run_dir: Path,
    env: dict | None = None,
    log_fn: Callable[[str], None] | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> int:
    """Run a guidellm benchmark as a K8s Job targeting the given vLLM pod.

    Args:
        pod_name: Name of the running vLLM pod to benchmark against.
        config: Benchmark config dict with keys: profile, max_requests, max_seconds, data, rate.
        run_dir: Local directory for results (benchmarks.json will be copied here).
        env: Environment dict (must include KUBECONFIG).
        log_fn: Logging callback; defaults to print.
        progress_callback: Called with completed request count as guidellm progresses.

    Returns 0 on success, non-zero on failure.
    """
    env = env or os.environ.copy()
    if log_fn is None:
        log_fn = print

    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Get vLLM pod IP
    try:
        target_ip = get_pod_ip(pod_name, env)
    except RuntimeError as e:
        log_fn(f"ERROR: {e}")
        return 1
    target_url = f"http://{target_ip}:8000"
    log_fn(f"vLLM pod {pod_name} -> {target_url}")

    # 2. Create benchmark job
    short_ts = str(int(time.time()))[-6:]
    job_name = f"bench-{short_ts}"
    manifest = _build_job_manifest(job_name, target_url, config)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, dir=str(run_dir),
    ) as f:
        yaml.dump(manifest, f)
        manifest_path = f.name

    try:
        subprocess.run(
            ["kubectl", "delete", "job", job_name, "--ignore-not-found=true"],
            capture_output=True, timeout=30, env=env,
        )
        r = subprocess.run(
            ["kubectl", "apply", "-f", manifest_path],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode != 0:
            log_fn(f"Failed to create benchmark job: {r.stderr}")
            return 1
        log_fn(f"Created benchmark job: {job_name}")
    finally:
        os.unlink(manifest_path)

    # 3. Wait for job pod to appear
    try:
        job_pod = _get_job_pod(job_name, env)
        log_fn(f"Benchmark pod: {job_pod}")
    except RuntimeError as e:
        log_fn(str(e))
        _cleanup_job(job_name, env)
        return 1

    # 4. Wait for pod to start running
    for _ in range(120):
        r = subprocess.run(
            ["kubectl", "get", "pod", job_pod, "-o", "jsonpath={.status.phase}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        phase = r.stdout.strip()
        if phase in ("Running", "Succeeded", "Failed"):
            break
        time.sleep(2)
    else:
        log_fn(f"Benchmark pod stuck in phase: {phase}")
        _cleanup_job(job_name, env)
        return 1

    # 5. Stream logs and wait for completion
    benchmark_live = run_dir / "benchmark_live.txt"
    max_seconds = int(config.get("max_seconds") or 300)
    abs_timeout = max_seconds * 3 + 600

    log_fn(f"Streaming benchmark logs (abs timeout: {abs_timeout}s)...")

    log_lines: list[str] = []
    last_completed = [0]
    done = threading.Event()

    logs_proc = subprocess.Popen(
        ["kubectl", "logs", "-f", job_pod],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )

    def reader() -> None:
        try:
            if logs_proc.stdout:
                for line in logs_proc.stdout:
                    log_lines.append(line)
                    n = parse_completed_count(line)
                    if n is not None and n > last_completed[0]:
                        last_completed[0] = n
                        if progress_callback:
                            progress_callback(n)
                    with open(benchmark_live, "a", encoding="utf-8") as bf:
                        bf.write(line)
        except Exception:
            pass
        finally:
            done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    start = time.monotonic()
    exit_code = 1

    while not done.is_set():
        elapsed = time.monotonic() - start
        if elapsed > abs_timeout:
            log_fn(f"Benchmark timed out after {int(elapsed)}s")
            break
        time.sleep(5)

        r = subprocess.run(
            ["kubectl", "get", "job", job_name, "-o",
             "jsonpath={.status.succeeded},{.status.failed}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        parts = r.stdout.strip().split(",")
        succeeded = parts[0] if len(parts) > 0 else ""
        failed = parts[1] if len(parts) > 1 else ""

        if succeeded == "1":
            log_fn("Benchmark job completed successfully")
            exit_code = 0
            break
        if failed == "1":
            log_fn("Benchmark job failed")
            exit_code = 1
            break

    # Final status check: the log reader may have exited (pod done) before
    # the loop could poll job status. Check once more.
    if exit_code != 0:
        time.sleep(2)
        r = subprocess.run(
            ["kubectl", "get", "job", job_name, "-o",
             "jsonpath={.status.succeeded},{.status.failed}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        parts = r.stdout.strip().split(",")
        if len(parts) > 0 and parts[0] == "1":
            log_fn("Benchmark job completed successfully (final check)")
            exit_code = 0
        elif len(parts) > 1 and parts[1] == "1":
            log_fn("Benchmark job failed (final check)")

    done.wait(timeout=10)
    if logs_proc.poll() is None:
        logs_proc.terminate()

    # 6. Extract results — do a final non-streaming kubectl logs to get
    # complete output (streaming logs can miss the tail on pod exit).
    if exit_code == 0:
        log_fn("Extracting benchmark results from job output...")
        # Try final non-streaming fetch first (most reliable)
        try:
            final_logs = subprocess.run(
                ["kubectl", "logs", job_pod],
                capture_output=True, text=True, timeout=60, env=env,
            )
            if final_logs.returncode == 0 and final_logs.stdout:
                full_output = final_logs.stdout
            else:
                full_output = "".join(log_lines)
        except Exception:
            full_output = "".join(log_lines)

        start_idx = full_output.find(_RESULTS_MARKER_START)
        end_idx = full_output.find(_RESULTS_MARKER_END)
        if start_idx >= 0 and end_idx > start_idx:
            json_text = full_output[start_idx + len(_RESULTS_MARKER_START):end_idx].strip()
            try:
                json.loads(json_text)  # validate
                (run_dir / "benchmarks.json").write_text(json_text)
                log_fn("Results extracted successfully")
            except json.JSONDecodeError as e:
                log_fn(f"Warning: could not parse benchmarks JSON: {e}")
                exit_code = 1
        else:
            log_fn("Warning: benchmarks JSON markers not found in job output")
            exit_code = 1

    # Append guidellm output to run.log
    if log_lines:
        run_log = run_dir / "run.log"
        with open(run_log, "a", encoding="utf-8") as f:
            f.write("\n--- guidellm stdout (K8s Job) ---\n")
            f.writelines(log_lines)

    # 7. Cleanup
    _cleanup_job(job_name, env)

    return exit_code
