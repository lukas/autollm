#!/usr/bin/env python3
"""
Serve results and provide API for the AI optimizer agent.

Endpoints: GET /, /api/agent/logs, /api/agent/benchmark-progress, /api/runs
           POST /api/agent/start, /api/agent/stop
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"
AGENT_LOG_FILE = RESULTS_DIR / "ai_optimizer_output.txt"
STATE_FILE = RESULTS_DIR / "ai_optimizer_state.json"
BENCHMARK_LIVE_FILE = RESULTS_DIR / "benchmark_live.txt"
AGENT_PROCESS: subprocess.Popen | None = None
AGENT_LOCK = threading.Lock()


class ResultsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RESULTS_DIR), **kwargs)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/ai_optimizer.html")
            self.end_headers()
            return
        if path == "/api/agent/logs":
            self._api_logs()
            return
        if path == "/api/agent/benchmark-progress":
            self._api_benchmark_progress()
            return
        if path == "/api/runs":
            self._api_runs()
            return
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/agent/start":
            self._api_start()
        elif path == "/api/agent/stop":
            self._api_stop()
        else:
            self.send_error(404)

    def _api_start(self):
        global AGENT_PROCESS
        benchmark_mode = "fast"
        if self.headers.get("Content-Length"):
            try:
                body = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8", errors="replace")
                if body:
                    data = json.loads(body)
                    benchmark_mode = data.get("benchmark", "fast")
                    if benchmark_mode not in ("fast", "full"):
                        benchmark_mode = "fast"
            except Exception:
                pass

        with AGENT_LOCK:
            if AGENT_PROCESS and AGENT_PROCESS.poll() is None:
                self._json_response({"ok": False, "error": "Agent already running"})
                return
            AGENT_LOG_FILE.write_text("")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["AI_OPTIMIZER_LOG"] = str(AGENT_LOG_FILE)
            env["BENCHMARK_MODE"] = benchmark_mode
            if "VLLM_CONFIG" not in env:
                env["VLLM_CONFIG"] = str(PROJECT_ROOT.parent / "runllm" / "vllm-qwen.yaml")
            proc = subprocess.Popen(
                ["uv", "run", "python", "-u", str(PROJECT_ROOT / "scripts" / "ai_benchmark_optimizer.py")],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            AGENT_PROCESS = proc
        self._json_response({"ok": True, "message": "Agent started"})

    def _api_logs(self):
        content = ""
        if AGENT_LOG_FILE.exists():
            try:
                content = AGENT_LOG_FILE.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        self._json_response({"logs": content})

    def _api_runs(self):
        runs = []
        if RUNS_DIR.exists():
            for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                meta, optimizer_meta, metrics = {}, {}, ""
                try:
                    if (run_dir / "run_metadata.json").exists():
                        meta = json.loads((run_dir / "run_metadata.json").read_text())
                except Exception:
                    pass
                try:
                    if (run_dir / "optimizer_metadata.json").exists():
                        optimizer_meta = json.loads((run_dir / "optimizer_metadata.json").read_text())
                except Exception:
                    pass
                try:
                    if (run_dir / "benchmarks.json").exists():
                        data = json.loads((run_dir / "benchmarks.json").read_text())
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
                run_rel = str(run_dir.relative_to(RESULTS_DIR))
                links = []
                if (run_dir / "summary.html").exists():
                    links.append({"label": "summary", "href": f"{run_rel}/summary.html"})
                if (run_dir / "vllm_config.yaml").exists():
                    links.append({"label": "config", "href": f"{run_rel}/vllm_config.yaml"})
                if (run_dir / "benchmarks.json").exists():
                    links.append({"label": "json", "href": f"{run_rel}/benchmarks.json"})
                if (run_dir / "run.log").exists():
                    links.append({"label": "log", "href": f"{run_rel}/run.log"})
                runs.append({
                    "timestamp": run_dir.name,
                    "description": meta.get("description", "") or run_dir.name,
                    "strategy": optimizer_meta.get("strategy", ""),
                    "changes_summary": optimizer_meta.get("changes_summary", ""),
                    "before_metrics": optimizer_meta.get("before_metrics", ""),
                    "after_metrics": optimizer_meta.get("after_metrics", ""),
                    "metrics": metrics,
                    "run_path": run_rel,
                    "links": links,
                })
        self._json_response({"runs": runs})

    def _api_benchmark_progress(self):
        content = ""
        if BENCHMARK_LIVE_FILE.exists():
            try:
                content = BENCHMARK_LIVE_FILE.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        self._json_response({"progress": content})

    def _api_stop(self):
        global AGENT_PROCESS
        with AGENT_LOCK:
            if AGENT_PROCESS and AGENT_PROCESS.poll() is None:
                AGENT_PROCESS.terminate()
                try:
                    AGENT_PROCESS.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    AGENT_PROCESS.kill()
                AGENT_PROCESS = None
            try:
                if STATE_FILE.exists():
                    state = json.loads(STATE_FILE.read_text())
                    state["current_run"] = None
                    STATE_FILE.write_text(json.dumps(state, indent=2))
            except Exception:
                pass
            self._json_response({"ok": True, "message": "Agent stopped"})

    def _json_response(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    port = 8765
    server = HTTPServer(("", port), ResultsHandler)
    print(f"Serving at http://localhost:{port}/")
    print("  Dashboard · Start/Stop · Benchmark runs")
    server.serve_forever()


if __name__ == "__main__":
    main()
