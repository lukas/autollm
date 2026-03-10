#!/usr/bin/env python3
"""
Benchmark harness: run Guideline benchmark, capture vLLM config, save to results/runs/.

Each run is saved to results/runs/YYYYMMDD_HHMMSS/. Requires vLLM port-forward.

Usage:
  python scripts/benchmark_harness.py [--description "My change"]
  VLLM_CONFIG=../runllm/vllm-qwen.yaml make benchmark-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "results" / "runs"
# Default: ../runllm/vllm-qwen.yaml when autollm is sibling of runllm
_DEFAULT_VLLM = PROJECT_ROOT.parent / "runllm" / "vllm-qwen.yaml"
VLLM_YAML = Path(os.environ.get("VLLM_CONFIG", str(_DEFAULT_VLLM))).resolve()
BENCHMARK_LIVE_FILE = PROJECT_ROOT / "results" / "benchmark_live.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark and save to timestamped dir")
    parser.add_argument(
        "--description", "-d",
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
        help="Quick benchmark: 5 requests, 30s max (for agent experimentation)",
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Capture vLLM config
    if VLLM_YAML.exists():
        shutil.copy(VLLM_YAML, run_dir / "vllm_config.yaml")
        _log(run_dir, "run.log", f"Captured vLLM config from {VLLM_YAML}")
    else:
        _log(run_dir, "run.log", f"VLLM config not found: {VLLM_YAML} (set VLLM_CONFIG)")

    # 2. Capture pod status (best-effort)
    try:
        result = subprocess.run(
            ["kubectl", "describe", "pod", "vllm-qwen"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            (run_dir / "pod_status.txt").write_text(result.stdout)
            _log(run_dir, "run.log", "Captured pod status")
    except Exception as e:
        _log(run_dir, "run.log", f"Could not capture pod status: {e}")

    # 3. Write run metadata
    metadata = {
        "timestamp": ts,
        "description": args.description,
        "vllm_config": str(VLLM_YAML),
    }
    (run_dir / "run_metadata.json").write_text(
        __import__("json").dumps(metadata, indent=2)
    )

    # 4. Run benchmark
    _log(run_dir, "run.log", "Starting Guideline benchmark...")
    if args.skip_port_forward:
        result = _run_guideline(run_dir, fast=args.fast)
    else:
        result = _run_with_port_forward(run_dir, fast=args.fast)

    if result != 0:
        _log(run_dir, "run.log", "Benchmark failed")
        sys.exit(result)

    _log(run_dir, "run.log", "Benchmark complete")

    # 5. Generate summary for this run
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"), str(run_dir)],
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    # 6. Regenerate runs index
    generate_runs_index()

    print(f"Run saved to {run_dir}")
    print(f"  summary:   {run_dir}/summary.html")
    print(f"  config:   {run_dir}/vllm_config.yaml")
    print(f"  index:    {RUNS_DIR}/index.html")


def _log(run_dir: Path, filename: str, msg: str) -> None:
    fp = run_dir / filename
    with open(fp, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    print(msg)


def _run_guideline(run_dir: Path, *, fast: bool = False) -> int:
    """Run Guideline benchmark via CLI, streaming output to benchmark_live.txt."""
    if fast:
        max_requests, max_seconds = "5", "30"
        data = "prompt_tokens=64,output_tokens=64"
    else:
        max_requests, max_seconds = "200", "600"
        data = "prompt_tokens=256,output_tokens=128"

    cmd = [
        "uv", "run", "guidellm", "benchmark",
        "--target", "http://localhost:8000",
        "--backend-args", '{"http2":false}',
        "--profile", "synchronous",
        "--request-type", "chat_completions",
        "--max-requests", max_requests,
        "--max-seconds", max_seconds,
        "--data", data,
        "--output-path", str(run_dir),
        "--outputs", "json", "--outputs", "csv",
        "--disable-progress",
    ]
    BENCHMARK_LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARK_LIVE_FILE.write_text(f"Starting benchmark ({max_requests} requests, {max_seconds}s max)...\n")

    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_lines = []
    try:
        if proc.stdout:
            for line in proc.stdout:
                log_lines.append(line)
                with open(BENCHMARK_LIVE_FILE, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
    except Exception:
        pass
    proc.wait()

    run_log = run_dir / "run.log"
    if run_log.exists() and log_lines:
        run_log.write_text(
            run_log.read_text() + "\n--- Guideline stdout ---\n" + "".join(log_lines),
            encoding="utf-8",
        )
    return proc.returncode


def _run_with_port_forward(run_dir: Path, *, fast: bool = False) -> int:
    """Start port-forward, run Guideline, stop port-forward."""
    import time
    import urllib.request

    subprocess.run(
        ["pkill", "-f", "kubectl port-forward vllm-qwen"],
        capture_output=True,
    )
    time.sleep(3)

    pf = subprocess.Popen(
        ["kubectl", "port-forward", "vllm-qwen", "8000:8000"],
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
            _log(run_dir, "run.log", "Timeout: vllm-qwen not reachable. Run: cd runllm && make forward")
            return 1

        return _run_guideline(run_dir, fast=fast)
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
                metrics = f"{lat*1000:.0f}ms · TTFT {ttft:.0f}ms · {tok:.0f} tok/s" if tok else f"{lat*1000:.0f}ms"
        except Exception:
            pass

        summary_link = f"{run_dir.name}/summary.html" if (run_dir / "summary.html").exists() else ""
        config_link = f"{run_dir.name}/vllm_config.yaml" if (run_dir / "vllm_config.yaml").exists() else ""

        rows.append({
            "ts": run_dir.name,
            "desc": desc,
            "metrics": metrics,
            "summary_link": summary_link,
            "config_link": config_link,
        })

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
            __import__("json").dumps({"timestamp": ts, "description": sys.argv[2] if len(sys.argv) > 2 else "imported", "imported": True}, indent=2)
        )
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"), str(run_dir)],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        generate_runs_index()
        print(f"Imported to {run_dir}")
    else:
        main()
