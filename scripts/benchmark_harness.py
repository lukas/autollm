#!/usr/bin/env python3
"""
Benchmark harness: run Guideline benchmark, capture vLLM config, save to results/runs/.

Each run is saved to results/runs/YYYYMMDD_HHMMSS/. Requires vLLM port-forward.

Usage:
  python scripts/benchmark_harness.py [--description "My change"]
  VLLM_CONFIG=runllm/qwen2.5-1.5b/vllm-config.yaml make benchmark-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from benchmark_config import BENCHMARK_PRESETS, parse_completed_count
from model_variants import infer_backend
from vllm_profiling import VLLMProfiler, write_vllm_snapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "results" / "runs"
RUNLLM_ROOT = PROJECT_ROOT / "runllm"
_DEFAULT_VLLM = RUNLLM_ROOT / "qwen2.5-1.5b" / "vllm-config.yaml"
VLLM_YAML = Path(os.environ.get("VLLM_CONFIG", str(_DEFAULT_VLLM))).resolve()
RUNLLM_DIR = VLLM_YAML.parent  # model subdir containing Makefile
BENCHMARK_LIVE_FILE = PROJECT_ROOT / "results" / "benchmark_live.txt"


def _pod_name_from_yaml(yaml_path: Path) -> str:
    """Extract metadata.name from a K8s Pod YAML."""
    if yaml_path.exists():
        try:
            import yaml

            doc = yaml.safe_load(yaml_path.read_text())
            name = doc.get("metadata", {}).get("name", "")
            if name:
                return name
        except Exception:
            pass
    return "vllm"


VLLM_POD = os.environ.get("VLLM_POD") or _pod_name_from_yaml(VLLM_YAML)
BACKEND = infer_backend(VLLM_YAML.read_text() if VLLM_YAML.exists() else "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run benchmark and save to timestamped dir"
    )
    parser.add_argument(
        "--description",
        "-d",
        default="",
        help="Description of this run (e.g. 'baseline', 'increased TP to 2')",
    )
    parser.add_argument(
        "--skip-port-forward",
        action="store_true",
        help="Assume port-forward already running; only run Guideline (no kubectl)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Quick benchmark: 5 requests, 30s max (alias for --benchmark quick)",
    )
    parser.add_argument(
        "--benchmark",
        "-b",
        choices=list(BENCHMARK_PRESETS),
        default="medium",
        help="Preset: quick, sync, sweep, medium, or long",
    )
    parser.add_argument(
        "--profile",
        help="Override profile (synchronous, sweep, etc.)",
    )
    parser.add_argument(
        "--data",
        help="Override data config (e.g. prompt_tokens=64,output_tokens=64)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        help="Override max requests",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="Override max seconds",
    )
    parser.add_argument(
        "--start-llm",
        action="store_true",
        help="Start vLLM first (make -C runllm start) before benchmark",
    )
    parser.add_argument(
        "--run-dir",
        metavar="PATH",
        help="Output directory for this run (default: results/runs/YYYYMMDD_HHMMSS)",
    )
    args = parser.parse_args()

    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        skip_index = True
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / ts
        skip_index = False
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Capture vLLM config
    if VLLM_YAML.exists():
        shutil.copy(VLLM_YAML, run_dir / "vllm_config.yaml")
        _log(run_dir, "run.log", f"Captured vLLM config from {VLLM_YAML}")
    else:
        _log(
            run_dir, "run.log", f"VLLM config not found: {VLLM_YAML} (set VLLM_CONFIG)"
        )

    # 2. Capture pod status (best-effort)
    try:
        result = subprocess.run(
            ["kubectl", "describe", "pod", VLLM_POD],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            (run_dir / "pod_status.txt").write_text(result.stdout)
            _log(run_dir, "run.log", "Captured pod status")
    except Exception as e:
        _log(run_dir, "run.log", f"Could not capture pod status: {e}")

    # Resolve benchmark config
    preset = BENCHMARK_PRESETS.get(
        "quick" if args.fast else args.benchmark, BENCHMARK_PRESETS["medium"]
    )
    cfg = {
        "profile": args.profile or str(preset["profile"]),
        "max_requests": str(args.max_requests)
        if args.max_requests is not None
        else preset["max_requests"],
        "max_seconds": str(args.max_seconds)
        if args.max_seconds is not None
        else str(preset["max_seconds"]),
        "rate": preset.get("rate"),
        "data": args.data or str(preset["data"]),
    }

    # 3. Write run metadata
    metadata = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S") if args.run_dir else ts,
        "description": args.description,
        "backend": BACKEND,
        "benchmark": args.benchmark if not args.fast else "quick",
        "benchmark_config": cfg,
        "vllm_config": str(VLLM_YAML),
    }
    (run_dir / "run_metadata.json").write_text(
        __import__("json").dumps(metadata, indent=2)
    )

    # 4. Optionally start LLM
    pf_proc = None
    profiler: VLLMProfiler | None = None
    if args.start_llm:
        _log(
            run_dir,
            "run.log",
            f"Starting {BACKEND} runllm pod={VLLM_POD} dir={RUNLLM_DIR}...",
        )
        proc = subprocess.Popen(
            ["make", "apply", f"VLLM_POD={VLLM_POD}"],
            cwd=str(RUNLLM_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        out_lines = []
        if proc.stdout:
            for line in proc.stdout:
                out_lines.append(line)
                with open(run_dir / "run.log", "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                print(line, end="")
        proc.wait()
        if proc.returncode != 0:
            _log(run_dir, "run.log", f"runllm apply failed: exit {proc.returncode}")
            sys.exit(proc.returncode)

        _log(run_dir, "run.log", "Waiting for pod to become ready...")
        r = subprocess.run(
            [
                "kubectl",
                "wait",
                "--for=condition=Ready",
                f"pod/{VLLM_POD}",
                "--timeout=600s",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            _log(
                run_dir, "run.log", f"Pod did not become ready: {r.stderr or r.stdout}"
            )
            sys.exit(1)

        _log(run_dir, "run.log", "Pod ready, waiting for vLLM health...")
        _health_iters = 180
        try:
            import yaml as _yaml
            _hc_gpu = int(
                _yaml.safe_load(VLLM_YAML.read_text())
                .get("spec", {}).get("containers", [{}])[0]
                .get("resources", {}).get("limits", {}).get("nvidia.com/gpu", 1)
            )
        except Exception:
            _hc_gpu = 1
        if _hc_gpu >= 8:
            _health_iters = 1350  # 45 min for very large models (Kimi-K2.5 safetensors ~35 min)
        elif _hc_gpu >= 4:
            _health_iters = 360  # 12 min for large models
        for i in range(_health_iters):
            hr = subprocess.run(
                [
                    "kubectl",
                    "exec",
                    VLLM_POD,
                    "--",
                    "curl",
                    "-sf",
                    "http://localhost:8000/health",
                ],
                capture_output=True,
                timeout=10,
            )
            if hr.returncode == 0:
                break
            if i == _health_iters - 1:
                _log(run_dir, "run.log", f"Health check timed out after {_health_iters * 2 // 60} min")
                sys.exit(1)
            time.sleep(2)

        _log(run_dir, "run.log", "vLLM healthy, starting port-forward...")
        subprocess.run(
            ["pkill", "-f", f"kubectl port-forward {VLLM_POD}"], capture_output=True
        )
        time.sleep(1)
        pf_proc = subprocess.Popen(
            ["kubectl", "port-forward", VLLM_POD, "8000:8000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        _log(run_dir, "run.log", "vLLM ready")

    # 5. Run benchmark
    profiler = VLLMProfiler(
        pod_name=VLLM_POD,
        run_dir=run_dir,
        env=os.environ.copy(),
        yaml_path=VLLM_YAML,
        interval_sec=float(os.environ.get("VLLM_PROFILE_INTERVAL_SEC", "5")),
        log_fn=lambda msg: _log(run_dir, "run.log", msg),
    )
    profiler.start()
    _log(
        run_dir,
        "run.log",
        f"Starting Guideline benchmark: profile={cfg['profile']} {cfg['max_requests'] or '?'} req, {cfg['max_seconds']}s max...",
    )
    print(
        "[Guideline] Running benchmark now (you will see output after each request completes)..."
    )
    try:
        if args.skip_port_forward or args.start_llm:
            result = _run_guideline(run_dir, config=cfg)
        else:
            result = _run_with_port_forward(run_dir, config=cfg)
    finally:
        if profiler is not None:
            profiler.stop()
            profiler = None
        write_vllm_snapshot(VLLM_POD, run_dir, os.environ.copy())
        if pf_proc and pf_proc.poll() is None:
            pf_proc.terminate()

    if result != 0:
        _log(run_dir, "run.log", "Benchmark failed")
        sys.exit(result)

    _log(run_dir, "run.log", "Benchmark complete")

    # 6. Generate summary for this run
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"),
            str(run_dir),
        ],
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    # 7. Regenerate runs index (skip when --run-dir used for sweep)
    if not skip_index:
        generate_runs_index()

    print(f"Run saved to {run_dir}")
    print(f"  summary:   {run_dir}/summary.html")
    print(f"  config:   {run_dir}/vllm_config.yaml")
    if not skip_index:
        print(f"  index:    {RUNS_DIR}/index.html")


def _log(run_dir: Path, filename: str, msg: str) -> None:
    fp = run_dir / filename
    with open(fp, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    print(msg)


def _run_guideline(run_dir: Path, *, config: dict) -> int:
    """Run Guideline benchmark via CLI, streaming output to benchmark_live.txt.
    Prints after each request completes; aborts if a single request exceeds 10s."""
    profile = config["profile"]
    max_requests = config["max_requests"]
    max_seconds = config["max_seconds"]
    data = config["data"]

    cmd = [
        "uv",
        "run",
        "guidellm",
        "benchmark",
        "--target",
        "http://localhost:8000",
        "--backend-args",
        '{"http2":false}',
        "--profile",
        profile,
        "--request-type",
        "chat_completions",
        "--max-seconds",
        max_seconds,
        "--data",
        data,
        "--output-dir",
        str(run_dir),
        "--outputs",
        "benchmarks.json",
        "--outputs",
        "benchmarks.csv",
        "--disable-console-interactive",
        "--processor-args",
        '{"trust_remote_code": true}',
    ]
    if max_requests:
        cmd.extend(["--max-requests", max_requests])
    rate = config.get("rate")
    if rate:
        cmd.extend(["--rate", rate])
    BENCHMARK_LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARK_LIVE_FILE.write_text(
        f"Starting benchmark (profile={profile}, {max_requests or '?'} req, {max_seconds}s max)...\n"
    )

    env = os.environ.copy()
    env["GUIDELLM__MP_CONTEXT_TYPE"] = "fork"
    env["HF_HUB_TRUST_REMOTE_CODE"] = "1"

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    if proc.pid:
        _log(
            run_dir, "run.log", f"Guideline benchmark process started (PID {proc.pid})"
        )
        print(f"[Guideline] Process started (PID {proc.pid})")
    log_lines: list[str] = []
    last_completed: list[int] = [0]  # mutable so thread can update
    last_completed_ts: list[float] = [0.0]
    last_output_ts: list[float] = [time.monotonic()]
    done = threading.Event()

    max_req = int(max_requests) if max_requests else None

    setup_complete = threading.Event()

    def reader() -> None:
        try:
            if proc.stdout:
                for line in proc.stdout:
                    log_lines.append(line)
                    last_output_ts[0] = time.monotonic()
                    if "starting benchmarks" in line.lower():
                        setup_complete.set()
                        print(f"[Guideline] Setup phase done, benchmark starting...")
                    completed = parse_completed_count(line)
                    if completed is not None:
                        if max_req is not None and completed > max_req:
                            completed = max_req
                        if completed > last_completed[0]:
                            last_completed[0] = completed
                            last_completed_ts[0] = time.monotonic()
                            print(f"[Guideline] Request {completed} complete")
                    with open(BENCHMARK_LIVE_FILE, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
        except Exception:
            pass
        finally:
            done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    start_ts = time.monotonic()
    stalled_reason: str | None = None
    while not done.is_set() and proc.poll() is None:
        time.sleep(1)
        now = time.monotonic()
        elapsed = now - start_ts
        # Timeouts scale with model size — large models (4+ GPUs) need more time
        try:
            import yaml as _y

            _gpu_count = int(
                _y.safe_load(VLLM_YAML.read_text())
                .get("spec", {})
                .get("containers", [{}])[0]
                .get("resources", {})
                .get("limits", {})
                .get("nvidia.com/gpu", 1)
            )
        except Exception:
            _gpu_count = 1
        if _gpu_count >= 4:
            _no_output_timeout = 600
            _stall_timeout = 600
        elif _gpu_count >= 2:
            _no_output_timeout = 120
            _stall_timeout = 60
        else:
            _no_output_timeout = 60
            _stall_timeout = 30
        _abs_timeout = int(max_seconds) * 3 + 300 if max_seconds else 1800

        if (run_dir / "benchmarks.json").exists() or (
            run_dir / "benchmark.json"
        ).exists():
            break
        if elapsed > _no_output_timeout and last_output_ts[0] <= start_ts:
            stalled_reason = f"no output after {_no_output_timeout}s (guideline may not have started)"
            break
        if elapsed > _abs_timeout:
            stalled_reason = f"absolute timeout after {int(elapsed)}s"
            break

    if stalled_reason:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        diag = (
            f"stall_reason={stalled_reason} | "
            f"elapsed={time.monotonic() - start_ts:.1f}s | "
            f"completed={last_completed[0]} | "
            f"setup_done={setup_complete.is_set()} | "
            f"last_output_age={time.monotonic() - last_output_ts[0]:.1f}s | "
            f"output_lines={len(log_lines)}"
        )
        _log(run_dir, "run.log", f"Guideline benchmark stopped: {diag}")
        print(f"[Guideline] Stopped: {diag}")

    done.wait(timeout=2)
    if proc.poll() is None:
        proc.wait()

    run_log = run_dir / "run.log"
    if run_log.exists() and log_lines:
        run_log.write_text(
            run_log.read_text() + "\n--- Guideline stdout ---\n" + "".join(log_lines),
            encoding="utf-8",
        )
    # Guideline may write benchmark.json (singular); ensure benchmarks.json exists
    if (
        proc.returncode == 0
        and (run_dir / "benchmark.json").exists()
        and not (run_dir / "benchmarks.json").exists()
    ):
        shutil.copy(run_dir / "benchmark.json", run_dir / "benchmarks.json")
    return proc.returncode if proc.returncode is not None else 1


def _run_with_port_forward(run_dir: Path, *, config: dict) -> int:
    """Start port-forward, run Guideline, stop port-forward."""
    import time
    import urllib.request

    subprocess.run(
        ["pkill", "-f", f"kubectl port-forward {VLLM_POD}"],
        capture_output=True,
    )
    time.sleep(3)

    pf = subprocess.Popen(
        ["kubectl", "port-forward", VLLM_POD, "8000:8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    try:
        for i in range(30):
            try:
                urllib.request.urlopen("http://localhost:8000/health", timeout=5)
                break
            except Exception:
                time.sleep(4)
        else:
            _log(
                run_dir,
                "run.log",
                f"Timeout: {VLLM_POD} not reachable. Run: cd runllm && make forward",
            )
            return 1

        return _run_guideline(run_dir, config=config)
    finally:
        pf.terminate()
        pf.wait(timeout=5)


def generate_runs_index() -> None:
    """Generate results/runs/index.html listing all runs."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = sorted(RUNS_DIR.iterdir(), reverse=True)
    runs = [d for d in runs if d.is_dir() and (d / "run_metadata.json").exists()]

    rows = []
    for run_dir in runs:
        meta = {}
        try:
            meta = __import__("json").loads((run_dir / "run_metadata.json").read_text())
        except Exception:
            pass
        desc = meta.get("description", "") or run_dir.name
        metrics = ""
        try:
            data = __import__("json").loads((run_dir / "benchmarks.json").read_text())
            b = data.get("benchmarks", [{}])[0]
            m = b.get("metrics", {})

            def _s(k, sk="successful"):
                o = m.get(k, {})
                return (o.get(sk) or {}).get("mean") if isinstance(o, dict) else None

            lat = _s("request_latency")
            ttft = _s("time_to_first_token_ms")
            tok = _s("tokens_per_second")
            if lat is not None:
                metrics = (
                    f"{lat * 1000:.0f}ms · TTFT {ttft:.0f}ms · {tok:.0f} tok/s"
                    if tok
                    else f"{lat * 1000:.0f}ms"
                )
        except Exception:
            pass

        summary_link = (
            f"{run_dir.name}/summary.html"
            if (run_dir / "summary.html").exists()
            else ""
        )
        config_link = (
            f"{run_dir.name}/vllm_config.yaml"
            if (run_dir / "vllm_config.yaml").exists()
            else ""
        )

        rows.append(
            {
                "ts": run_dir.name,
                "desc": desc,
                "metrics": metrics,
                "summary_link": summary_link,
                "config_link": config_link,
            }
        )

    html = _index_html(rows)
    (RUNS_DIR / "index.html").write_text(html)


def _index_html(rows: list) -> str:
    table_rows = ""
    for r in rows:
        links = []
        if r["summary_link"]:
            links.append(f'<a href="{r["summary_link"]}">summary</a>')
        if r["config_link"]:
            links.append(f'<a href="{r["config_link"]}">config</a>')
        links_str = " · ".join(links) if links else "—"
        table_rows += f"""
        <tr>
            <td>{r["ts"]}</td>
            <td>{r["desc"]}</td>
            <td>{r["metrics"] or "—"}</td>
            <td>{links_str}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Benchmark Runs</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ color: #333; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 10px 12px; text-align: left; }}
    th {{ background: #f5f5f5; font-weight: 600; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    a {{ color: #2A8EFD; }}
  </style>
</head>
<body>
  <h1>Benchmark Run History</h1>
  <p>Each run saved to <code>results/runs/YYYYMMDD_HHMMSS/</code></p>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th>
        <th>Description</th>
        <th>Metrics</th>
        <th>Links</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--index-only":
        generate_runs_index()
        print(f"Index: {RUNS_DIR / 'index.html'}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--import":
        # Copy results/ into new run dir (legacy)
        src = PROJECT_ROOT / "results"
        if not (src / "benchmarks.json").exists():
            print("No results/benchmarks.json found.")
            sys.exit(1)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / ts
        run_dir.mkdir(parents=True, exist_ok=True)
        for name in ("benchmarks.json", "benchmarks.csv", "benchmarks.html"):
            f = src / name
            if f.exists():
                shutil.copy(f, run_dir / name)
        if VLLM_YAML.exists():
            shutil.copy(VLLM_YAML, run_dir / "vllm_config.yaml")
        (run_dir / "run_metadata.json").write_text(
            __import__("json").dumps(
                {
                    "timestamp": ts,
                    "description": sys.argv[2] if len(sys.argv) > 2 else "imported",
                    "imported": True,
                },
                indent=2,
            )
        )
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"),
                str(run_dir),
            ],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        generate_runs_index()
        print(f"Imported to {run_dir}")
    else:
        main()
