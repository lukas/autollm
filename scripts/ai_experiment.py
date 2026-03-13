#!/usr/bin/env python3
"""
AI experiment: show agent (Opus/Codex) runllm code + benchmark data, get suggested changes,
write modified runllm to results/runs or results/sweep-NAME/ only (never project root), deploy, benchmark.

Usage:
  AI_PROVIDER=anthropic AI_MODEL=claude-opus-4-6 make experiment
  AI_PROVIDER=openai AI_MODEL=gpt-4o make experiment
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from benchmark_config import BENCHMARK_MAX_REQUESTS, BENCHMARK_PRESETS
from sweep_utils import completed_request_count, is_valid_run, metric_mean, sweep_objective, sweep_ranking_label

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Track active pods for cleanup on exit/Ctrl+C
_active_pods: list[str] = []
_cleanup_env: dict[str, str] = {}


def _cleanup_pods_on_exit():
    """Delete any pods we created, called on exit or signal."""
    for pod_name in _active_pods:
        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--wait=false"],
                capture_output=True, timeout=10, env=_cleanup_env or os.environ.copy(),
            )
        except Exception:
            pass
    _active_pods.clear()


atexit.register(_cleanup_pods_on_exit)


def _handle_signal(signum, frame):
    _cleanup_pods_on_exit()
    sys.exit(128 + signum)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)
RUNLLM = PROJECT_ROOT / "runllm"
RUNS_DIR = PROJECT_ROOT / "results" / "runs"
RESULTS_DIR = PROJECT_ROOT / "results"
PROGRESS_FILE = PROJECT_ROOT / "results" / "experiment_progress.json"

# After this many seconds, we inspect progress; if still in a long phase, abort and log.
INSPECT_AFTER_SEC = int(os.environ.get("EXPERIMENT_INSPECT_AFTER_SEC", "180"))

# If query count unchanged for this many seconds during benchmark, assume stuck and abort.
QUERY_STALE_SEC = int(os.environ.get("EXPERIMENT_QUERY_STALE_SEC", "30"))

# Timeout for sample query before benchmark (must complete or we abort)
SAMPLE_QUERY_TIMEOUT = int(os.environ.get("EXPERIMENT_SAMPLE_QUERY_TIMEOUT", "30"))

def _metric(m: dict, k: str, sub: str = "successful") -> float | None:
    o = m.get(k, {})
    suc = o.get(sub) if isinstance(o, dict) else {}
    return suc.get("mean") if isinstance(suc, dict) else None


def _fmt_summary(m: dict) -> str:
    lat = _metric(m, "request_latency")
    ttft = _metric(m, "time_to_first_token_ms")
    tok = _metric(m, "tokens_per_second")
    rps = _metric(m, "requests_per_second")
    parts = []
    if lat is not None:
        parts.append(f"Latency: {lat*1000:.0f}ms")
    if ttft is not None:
        parts.append(f"TTFT: {ttft:.0f}ms")
    if tok is not None:
        parts.append(f"Throughput: {tok:.0f} tok/s")
    if rps is not None:
        parts.append(f"Req/s: {rps:.1f}")
    return " | ".join(parts) if parts else "—"


def _get_sample_benchmark_data(runs_dir: Path | None = None) -> str:
    """Summarized benchmark data from runs in runs_dir (default: RUNS_DIR)."""
    base = runs_dir or RUNS_DIR
    if not base.exists():
        return "No previous benchmark data."
    runs = sorted(
        [d for d in base.iterdir() if d.is_dir() and (d / "benchmarks.json").exists()],
        key=lambda d: d.name,
        reverse=True,
    )[:5]
    lines = []
    for d in runs:
        try:
            data = json.loads((d / "benchmarks.json").read_text())
            b = data.get("benchmarks", [{}])[0]
            m = b.get("metrics", {})
            meta = {}
            if (d / "run_metadata.json").exists():
                meta = json.loads((d / "run_metadata.json").read_text())
            desc = meta.get("description", d.name)
            lines.append(f"- {d.name} ({desc}): {_fmt_summary(m)}")
        except Exception:
            pass
    return "\n".join(lines) if lines else "No valid benchmark data."


def _read_results_txt(results_path: Path | None = None) -> str:
    """Previous experiment summaries from results.txt."""
    path = results_path or (RESULTS_DIR / "results.txt")
    if not path.exists():
        return "No previous experiments."
    return path.read_text()[-8000:]  # last ~8k chars


def _get_retros(runs_base: Path | None) -> str:
    """Collect RETRO.md from run directories for context to future agents."""
    if not runs_base or not runs_base.exists():
        return ""
    retros = []
    for d in sorted(runs_base.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        retro_file = d / "RETRO.md"
        if retro_file.exists():
            try:
                content = retro_file.read_text().strip()
                if content:
                    retros.append(f"\n--- Retro from {d.name} ({d.relative_to(runs_base)}) ---\n{content[:4000]}")
            except Exception:
                pass
    return "\n".join(retros[:5]) if retros else ""  # max 5 retros to avoid prompt bloat


def _extract_vllm_args(config_text: str) -> str:
    """Extract just the image and arg list from a vLLM pod YAML."""
    try:
        data = yaml.safe_load(config_text) or {}
    except Exception:
        return ""
    containers = (((data.get("spec") or {}).get("containers")) or [])
    if not containers:
        return ""
    container = containers[0] or {}
    image = str(container.get("image", "")).strip()
    args_list = []
    args = container.get("args") or []
    idx = 0
    while idx < len(args):
        item = str(args[idx]).strip()
        if item.startswith("--"):
            if idx + 1 < len(args) and not str(args[idx + 1]).strip().startswith("--"):
                args_list.append(f"{item} {str(args[idx + 1]).strip()}")
                idx += 2
                continue
            args_list.append(item)
        idx += 1
    return f"image={image}  args: {', '.join(args_list)}" if args_list else f"image={image}"


def _extract_config_state(config_text: str) -> dict[str, str | bool]:
    """Extract image, args, and env vars from the pod YAML for diffing."""
    state: dict[str, str | bool] = {}
    try:
        data = yaml.safe_load(config_text) or {}
    except Exception:
        return state
    containers = (((data.get("spec") or {}).get("containers")) or [])
    if not containers:
        return state
    container = containers[0] or {}
    image = container.get("image")
    if image:
        state["image"] = str(image).strip()

    args = container.get("args") or []
    idx = 0
    while idx < len(args):
        key = str(args[idx]).strip()
        if key.startswith("--"):
            state[f"arg:{key}"] = True
            if idx + 1 < len(args) and not str(args[idx + 1]).strip().startswith("--"):
                state[f"arg:{key}"] = str(args[idx + 1]).strip()
                idx += 2
                continue
        idx += 1

    for env_var in container.get("env") or []:
        name = str(env_var.get("name", "")).strip()
        if not name:
            continue
        if "value" in env_var:
            state[f"env:{name}"] = str(env_var["value"]).strip()
        elif "valueFrom" in env_var:
            state[f"env:{name}"] = "(valueFrom)"
        else:
            state[f"env:{name}"] = "(set)"
    return state


def _format_state_value(value: str | bool | None) -> str:
    if value is True:
        return "enabled"
    if value in (None, ""):
        return "absent"
    return str(value)


def _summarize_config_changes(config_text: str, reference_text: str | None) -> list[str]:
    """Summarize config changes relative to a reference config."""
    if not config_text or not reference_text:
        return []
    current = _extract_config_state(config_text)
    reference = _extract_config_state(reference_text)
    changes = []
    for key in sorted(set(current) | set(reference)):
        before = reference.get(key)
        after = current.get(key)
        if before == after:
            continue
        if key == "image":
            label = "image"
        elif key.startswith("arg:"):
            label = key[4:]
        elif key.startswith("env:"):
            label = f"env {key[4:]}"
        else:
            label = key
        changes.append(f"{label}: {_format_state_value(before)} -> {_format_state_value(after)}")
    return changes


def _extract_no_config_change_reason(text: str) -> str | None:
    m = re.search(r"NO_CONFIG_CHANGE:\s*(.+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _get_experiment_leaderboard(runs_base: Path, project_root: Path) -> str:
    """Compact leaderboard ranked according to the sweep objective."""
    if not runs_base.exists():
        return "No experiments."
    dirs = [d for d in runs_base.iterdir() if d.is_dir() and not d.name.startswith(".")]
    sweep_name = runs_base.name.replace("sweep-", "")
    objective = sweep_objective(sweep_name)
    reference_config_text = None
    for cfg in ("baseline/vllm_config.yaml", "baseline/runllm/vllm-qwen.yaml"):
        fp = runs_base / cfg
        if fp.exists():
            reference_config_text = fp.read_text()
            break

    successes = []
    failures = []
    for d in dirs:
        meta = {}
        if (d / "run_metadata.json").exists():
            try:
                meta = json.loads((d / "run_metadata.json").read_text())
            except Exception:
                pass
        desc = meta.get("description", "")
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                if not is_valid_run(d, data):
                    n_completed = completed_request_count(data)
                    failures.append({
                        "name": d.name,
                        "desc": desc,
                        "result": f"insufficient benchmark traffic: only {n_completed} requests completed",
                        "changes": _summarize_config_changes(
                            next((fp.read_text() for cfg in ("vllm_config.yaml", "runllm/vllm-qwen.yaml")
                                  if (fp := d / cfg).exists()), ""),
                            reference_config_text,
                        ),
                    })
                    continue
                b = data.get("benchmarks", [{}])[0]
                m = b.get("metrics", {})
                metrics = _fmt_summary(m)
                if metrics and metrics != "—":
                    config_text = ""
                    for cfg in ("vllm_config.yaml", "runllm/vllm-qwen.yaml"):
                        fp = d / cfg
                        if fp.exists():
                            config_text = fp.read_text()
                            break
                    lat = metric_mean(m, "request_latency")
                    tok = metric_mean(m, "tokens_per_second")
                    ttft = metric_mean(m, "time_to_first_token_ms")
                    successes.append({"name": d.name, "metrics": metrics, "desc": desc,
                                      "config_summary": _extract_vllm_args(config_text) if config_text else "",
                                      "changes": _summarize_config_changes(config_text, reference_config_text),
                                      "latency": lat or 999,
                                      "throughput": tok or 0,
                                      "ttft": ttft or 999999,
                                      "path": str(d.relative_to(project_root))})
                    continue
            except Exception:
                pass
        # Failed or no metrics
        result = ""
        config_text = ""
        for cfg in ("vllm_config.yaml", "runllm/vllm-qwen.yaml"):
            fp = d / cfg
            if fp.exists():
                config_text = fp.read_text()
                break
        if (d / "run_metadata.json").exists():
            try:
                rm = json.loads((d / "run_metadata.json").read_text())
                result = rm.get("result", "")
            except Exception:
                pass
        if desc or result:
            failures.append({
                "name": d.name,
                "desc": desc,
                "result": result,
                "changes": _summarize_config_changes(config_text, reference_config_text),
            })

    if objective == "throughput":
        successes.sort(key=lambda x: (-x["throughput"], x["latency"]))
    elif objective == "ttft":
        successes.sort(key=lambda x: x["ttft"])
    else:
        successes.sort(key=lambda x: x["latency"])

    lines = []
    if successes:
        lines.append(f"LEADERBOARD (successful runs, ranked by {sweep_ranking_label(sweep_name)}):")
        lines.append("-" * 100)
        for s in successes[:10]:
            lines.append(f"{s['name']}  {s['metrics']}")
            if s["desc"]:
                lines.append(f"  Strategy: {s['desc']}")
            if s["changes"]:
                lines.append("  Changed knobs vs baseline:")
                for change in s["changes"]:
                    lines.append(f"    - {change}")
            lines.append(f"  Args: {s['config_summary']}")
            lines.append("")
        if len(successes) > 10:
            lines.append(f"... and {len(successes) - 10} more successful runs")

    if failures:
        failures_to_show = failures[-50:]
        lines.append(f"\nFailed runs ({len(failures)} total, showing last {len(failures_to_show)} — DO NOT repeat these strategies):")
        for f in failures_to_show:
            lines.append(f"  {f['name']}: {f['desc']}")
            if f["changes"]:
                lines.append("    Changed knobs vs baseline:")
                for change in f["changes"]:
                    lines.append(f"      - {change}")
            if f["result"]:
                lines.append(f"    Error: {f['result']}")

    return "\n".join(lines) if lines else "No experiments yet."


def _write_leaderboard_to_sweep(sweep_dir: Path) -> None:
    """Write the current leaderboard to sweep_dir/leaderboard.txt for easy viewing."""
    if not sweep_dir or not sweep_dir.exists():
        return
    leaderboard = _get_experiment_leaderboard(sweep_dir, PROJECT_ROOT)
    (sweep_dir / "leaderboard.txt").write_text(leaderboard)


def _get_best_config_yaml(runs_base: Path) -> str | None:
    """Get the full YAML of the best successful run for reference."""
    if not runs_base.exists():
        return None
    best_dir = None
    best_lat = 999.0
    for d in runs_base.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                m = data.get("benchmarks", [{}])[0].get("metrics", {})
                lat = _metric(m, "request_latency")
                if lat is not None and lat < best_lat:
                    best_lat = lat
                    best_dir = d
            except Exception:
                pass
    if best_dir:
        for cfg in ("vllm_config.yaml", "runllm/vllm-qwen.yaml"):
            fp = best_dir / cfg
            if fp.exists():
                return fp.read_text()[:2000]
    return None


def _get_workload_description(runs_base: Path) -> str:
    """Extract benchmark workload info (prompt tokens, output tokens, profile) from a benchmarks.json."""
    for d in sorted(runs_base.iterdir(), key=lambda x: x.name, reverse=True) if runs_base.exists() else []:
        if (d / "benchmarks.json").exists():
            try:
                data = json.loads((d / "benchmarks.json").read_text())
                a = data.get("args", {})
                b = data.get("benchmarks", [{}])[0]
                cfg = b.get("config", {})
                strat = cfg.get("strategy", {}).get("type_", a.get("profile", "unknown"))
                max_req = a.get("max_requests", "?")
                max_sec = a.get("max_seconds", "?")
                data_info = a.get("data", ["?"])
                return f"Profile: {strat}, max_requests={max_req}, max_seconds={max_sec}, data={data_info}"
            except Exception:
                pass
    return "unknown"


def _call_anthropic(prompt: str, model: str) -> str:
    from anthropic import Anthropic
    msg = Anthropic().messages.create(model=model, max_tokens=8192, messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text if msg.content else ""


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI()
    if "codex" in model.lower():
        r = client.responses.create(model=model, max_output_tokens=8192, input=[{"role": "user", "content": prompt}])
        return r.output_text if hasattr(r, "output_text") and r.output_text else ""
    r = client.chat.completions.create(model=model, max_tokens=8192, messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content if r.choices else ""


def _extract_code_block(text: str, lang: str = "") -> str | None:
    pattern = rf"```(?:{re.escape(lang)})?\s*\n(.*?)```" if lang else r"```\w*\s*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_yaml(text: str) -> str | None:
    for lang in ("yaml", "yml", ""):
        found = _extract_code_block(text, lang)
        if found and ("apiVersion:" in found or "kind:" in found):
            return found
    return None


def _extract_makefile(text: str) -> str | None:
    found = _extract_code_block(text, "makefile")
    if found:
        return found
    found = _extract_code_block(text, "Makefile")
    if found:
        return found
    return None


def _write_progress(phase: str, extra: dict | None = None) -> None:
    """Write current phase to progress file for inspection."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "phase": phase,
        "phase_started": datetime.now().isoformat(),
        "pid": os.getpid(),
    }
    if extra:
        data.update(extra)
    PROGRESS_FILE.write_text(json.dumps(data, indent=2))


def _log_run(run_dir: Path, msg: str, also_stdout: bool = True) -> None:
    """Append to run_dir/run.log and optionally print."""
    if run_dir:
        log_file = run_dir / "run.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    if also_stdout:
        print(msg)


def _elapsed_since(start: float) -> float:
    return time.time() - start


def _extract_description(text: str) -> str:
    # Fallback when agent doesn't provide summary
    m = re.search(r"(?:description|experiment|strategy):\s*(.+?)(?:```|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    return text[:300].strip()


def _ask_agent_summary(response: str, call_fn) -> str:
    """Ask agent for a concise 2-4 sentence summary of its proposal. Used for terminal display."""
    try:
        summary = call_fn(f"""You just proposed a vLLM config change. Here is your response:

{response[:4000]}

In 2-4 sentences, summarize: what you're changing and why it should help. Output only the summary, nothing else. Be concise for terminal display.""")
        return summary.strip() if summary else ""
    except Exception:
        return ""


def _check_abort(start: float, phase: str, last_progress: float | None = None) -> str | None:
    """Return abort message if we should abort, unless recent progress was made."""
    if INSPECT_AFTER_SEC <= 0:
        return None
    if _elapsed_since(start) < INSPECT_AFTER_SEC:
        return None
    if last_progress is not None and (time.time() - last_progress) < INSPECT_AFTER_SEC:
        return None
    return f"Aborted after {INSPECT_AFTER_SEC}s: stuck in phase '{phase}'"


# Patterns indicating infrastructure/Kubernetes setup errors (NOT fixable by changing vLLM YAML)
INFRASTRUCTURE_ERROR_PATTERNS = [
    "Forbidden",
    "Error from server (Forbidden)",
    "connection refused",
    "dial tcp",
    "RBAC",
    "Unauthorized",
    "get current server API",
]


def _is_infrastructure_error(result: str) -> bool:
    """Return True if the error is kubectl/K8s setup, not vLLM config."""
    r = result.lower()
    return any(p.lower() in r for p in INFRASTRUCTURE_ERROR_PATTERNS)


# Patterns that indicate vLLM failed to start (fatal config error, crash, etc.)
VLLM_FATAL_LOG_PATTERNS = [
    (re.compile(r"vllm: error: unrecognized arguments?", re.I), "unrecognized vLLM arguments"),
    (re.compile(r"error: (?:invalid|unsupported|unknown)", re.I), "invalid/unsupported option"),
    (re.compile(r"Traceback \(most recent call last\)", re.I), "Python traceback"),
    (re.compile(r"ModuleNotFoundError|ImportError", re.I), "import error"),
    (re.compile(r"RuntimeError:", re.I), "runtime error"),
    (re.compile(r"CUDA (?:out of memory|error)", re.I), "CUDA OOM/error"),
    (re.compile(r"exit code [1-9]\d*", re.I), "non-zero exit"),
]


def _find_free_port() -> int:
    """Find a free local port for port-forwarding."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _k8s_label_value(value: str) -> str:
    """Sanitize a value for Kubernetes labels."""
    value = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower())
    value = value.strip("-.")
    return value[:63] or "default"


def _rewrite_pod_name(yaml_path: Path, new_name: str, sweep: str | None = None) -> None:
    """Rewrite metadata.name and add labels for sweep discovery."""
    text = yaml_path.read_text()
    text = re.sub(r'(metadata:\s*\n\s*name:\s*)(\S+)', rf'\g<1>{new_name}', text)
    labels = {"autollm-managed": "true"}
    if sweep:
        labels["autollm-sweep"] = _k8s_label_value(sweep)
    quoted_labels = {k: json.dumps(v) for k, v in labels.items()}
    label_lines = "\n".join(f"    {k}: {v}" for k, v in quoted_labels.items())
    if re.search(r"metadata:\s*\n(?:\s+.+\n)*?\s+labels:\s*\n", text):
        for key, value in quoted_labels.items():
            pattern = rf"(metadata:\s*\n(?:\s+.+\n)*?\s+labels:\s*\n)"
            if re.search(rf"^\s+{re.escape(key)}:\s*", text, re.MULTILINE):
                text = re.sub(rf"(^\s+{re.escape(key)}:\s*).*$", rf"\1{value}", text, flags=re.MULTILINE)
            else:
                text = re.sub(pattern, rf"\1    {key}: {value}\n", text, count=1)
    else:
        text = re.sub(
            r"(metadata:\s*\n\s*name:\s*\S+\n)",
            rf"\1  labels:\n{label_lines}\n",
            text,
            count=1,
        )
    yaml_path.write_text(text)


def _fetch_and_check_logs(run_dir: Path, env: dict, logs_file: Path, pod_name: str = "vllm-qwen") -> str | None:
    """Fetch kubectl logs, append to logs_file, return error msg if fatal pattern found."""
    try:
        r = subprocess.run(
            ["kubectl", "logs", pod_name, "--all-containers=true", "--tail=200"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode != 0:
            return None
        text = (r.stdout or "") + (r.stderr or "")
        if not text.strip():
            return None
        with open(logs_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            f.write(text)
        for pat, label in VLLM_FATAL_LOG_PATTERNS:
            m = pat.search(text)
            if m:
                snippet = text[max(0, m.start() - 50) : m.end() + 150]
                return f"vLLM logs show {label}: {snippet[:300].strip()!r}"
    except Exception:
        pass
    return None


def _deploy_and_benchmark(
    experiment_dir: Path, benchmark: str, run_dir: Path, ts: str, sweep: str | None = None
) -> tuple[bool, str]:
    """Deploy from experiment_dir, run benchmark, stream logs to run_dir, track queries, abort if stuck.
    Uses a unique pod name and local port so multiple runs can execute in parallel."""
    start = time.time()
    vllm_yaml = experiment_dir / "vllm-qwen.yaml"
    env = os.environ.copy()
    env["VLLM_CONFIG"] = str(vllm_yaml)
    env["KUBECONFIG"] = os.environ.get("KUBECONFIG", "")
    pf = None
    bench_proc = None
    logs_proc = None

    # Unique pod name and port for parallel runs
    short_id = ts.replace("_", "")[-8:]  # e.g. "12112142" from "20260312_112142"
    pod_name = f"vllm-qwen-{short_id}"
    local_port = _find_free_port()
    _rewrite_pod_name(vllm_yaml, pod_name, sweep=sweep)
    _log_run(run_dir, f"Pod: {pod_name}, local port: {local_port}")

    # Register for cleanup on Ctrl+C / crash
    _active_pods.append(pod_name)
    _cleanup_env.update(env)

    run_dir.mkdir(parents=True, exist_ok=True)

    def _append_deploy_log(cmd: list, r: subprocess.CompletedProcess) -> None:
        with open(run_dir / "deploy.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {' '.join(cmd)} ---\n")
            f.write(f"returncode={r.returncode}\n")
            if r.stdout:
                f.write(r.stdout[:2000] + ("..." if len(r.stdout) > 2000 else "") + "\n")
            if r.stderr:
                f.write("STDERR: " + r.stderr[:1000] + "\n")

    def _cleanup(msg: str | None = None) -> tuple[bool, str] | None:
        for proc in (logs_proc, bench_proc, pf):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true"],
                capture_output=True, timeout=30, env=env,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--force", "--grace-period=0"],
                capture_output=True, timeout=30, env=env,
            )
        if pod_name in _active_pods:
            _active_pods.remove(pod_name)
        if msg:
            _write_progress("aborted", {"reason": msg})
            _log_run(run_dir, f"ABORTED: {msg}")
            return False, msg
        return None

    _write_progress("deploy_delete", {"experiment_dir": str(experiment_dir), "run_dir": str(run_dir), "pod_name": pod_name})
    _log_run(run_dir, "Deploy: delete + apply")

    for cmd, err in [
        (["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true"], "delete failed"),
        (["kubectl", "apply", "-f", str(vllm_yaml)], "apply failed"),
    ]:
        if m := _check_abort(start, "deploy"):
            return _cleanup(m)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        except subprocess.TimeoutExpired:
            if "delete" in cmd:
                # Force-delete on timeout and continue to apply
                subprocess.run(
                    ["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--force", "--grace-period=0"],
                    capture_output=True, text=True, timeout=30, env=env,
                )
                continue
            _cleanup()
            return False, f"{err}: timed out after 120s"
        _append_deploy_log(cmd, r)
        if r.returncode != 0:
            _cleanup()
            return False, f"{err}: {(r.stderr or r.stdout or '').strip()[:500]}"

    kubectl_logs_file = run_dir / "kubectl_logs.txt"
    kubectl_logs_file.write_text(f"--- logs started {datetime.now().isoformat()} ---\n")

    _write_progress("pod_wait", {})
    _log_run(run_dir, "Waiting for pod Ready...")
    for _ in range(20):
        if m := _check_abort(start, "pod_wait"):
            return _cleanup(m)
        if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
            return _cleanup(f"vLLM startup error (pod_wait): {err}")
        r = subprocess.run(
            ["kubectl", "wait", "--for=condition=Ready", f"pod/{pod_name}", "--timeout=30s"],
            capture_output=True, text=True, env=env,
        )
        _append_deploy_log(["kubectl", "wait", "..."], r)
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        return _cleanup(f"Pod not ready: {(r.stderr or r.stdout or '').strip()[:500]}")

    _write_progress("health_check", {})
    _log_run(run_dir, "Waiting for vLLM health...")
    health_start = time.time()
    for i in range(90):
        if m := _check_abort(start, "health_check"):
            return _cleanup(m)
        if i % 5 == 4:
            if err := _fetch_and_check_logs(run_dir, env, kubectl_logs_file, pod_name):
                return _cleanup(f"vLLM startup error (health_check): {err}")
        r = subprocess.run(
            ["kubectl", "exec", pod_name, "--", "curl", "-sf", "--max-time", "3", "http://localhost:8000/health"],
            capture_output=True, timeout=5, env=env,
        )
        if r.returncode == 0:
            _log_run(run_dir, f"vLLM ready ({time.time() - health_start:.0f}s)")
            break
        time.sleep(1)
    else:
        return _cleanup("vLLM did not become ready (health check timeout)")

    _write_progress("sample_query", {})
    _log_run(run_dir, "Running sample query...")
    model = "Qwen/Qwen2.5-1.5B-Instruct"
    try:
        text = vllm_yaml.read_text()
        m = re.search(r'--model["\']?\s*\n\s*-\s*["\']?([^"\'"\n\r]+)', text)
        if m:
            model = m.group(1).strip().rstrip("'\"")
    except Exception:
        pass
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 16,
    })
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "--", "curl", "-sf", "-X", "POST", "http://localhost:8000/v1/chat/completions",
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=SAMPLE_QUERY_TIMEOUT, env=env,
    )
    _append_deploy_log(["kubectl", "exec", pod_name, "--", "curl", "...", "sample query"], r)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:500]
        _cleanup()
        return False, f"Sample query failed (exit {r.returncode}): {err}"
    try:
        data = json.loads(r.stdout or "{}")
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content or not isinstance(content, str):
            _cleanup()
            return False, "Sample query returned empty or invalid response"
    except json.JSONDecodeError:
        _cleanup()
        return False, "Sample query returned invalid JSON"
    _log_run(run_dir, "Sample query OK (model responded)")

    _write_progress("port_forward", {})
    pf = subprocess.Popen(
        ["kubectl", "port-forward", pod_name, f"{local_port}:8000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    time.sleep(2)

    with open(kubectl_logs_file, "a", encoding="utf-8") as f:
        f.write(f"\n--- live stream started {datetime.now().isoformat()} ---\n")
    logs_proc = subprocess.Popen(
        ["kubectl", "logs", "-f", pod_name, "--all-containers=true"],
        stdout=open(kubectl_logs_file, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=env,
    )

    timeout_sec = 3600  # generous max; real timeout is QUERY_STALE_SEC (no progress for 30s)

    _write_progress("benchmark", {"timeout_sec": timeout_sec, "run_dir": str(run_dir)})
    _log_run(run_dir, f"Starting benchmark ({benchmark}), run_dir={run_dir}")

    bench_env = env.copy()
    bench_env["EXPERIMENT_RUN_DIR"] = str(run_dir)
    bench_env["EXPERIMENT_BENCHMARK"] = benchmark
    bench_env["EXPERIMENT_DESCRIPTION"] = f"ai_experiment {experiment_dir.name}"
    bench_env["EXPERIMENT_TARGET"] = f"http://localhost:{local_port}"

    guideline_script = PROJECT_ROOT / "scripts" / "run_guideline_experiment.py"
    bench_proc = subprocess.Popen(
        [sys.executable, str(guideline_script)],
        cwd=str(PROJECT_ROOT),
        env=bench_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    harness_out = run_dir / "harness_output.txt"
    last_queries = -1
    last_updated = time.time()
    last_wait_report = 0.0
    query_progress_file = run_dir / "query_progress.json"
    max_requests = BENCHMARK_MAX_REQUESTS.get(benchmark, 0)
    bench_start = time.time()
    last_harness_line = ""

    def _count_from_kubectl_logs() -> int:
        """Count actual chat completion requests (not health checks or model list)."""
        if not kubectl_logs_file.exists():
            return 0
        try:
            text = kubectl_logs_file.read_text(errors="replace")
            return len(re.findall(r"POST /v1/chat/completions.* 200", text))
        except Exception:
            return 0

    stdout_lines: list[str] = []

    def _read_stdout():
        if bench_proc.stdout:
            for line in bench_proc.stdout:
                stdout_lines.append(line)

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()

    try:
        with open(harness_out, "w", encoding="utf-8") as out:
            poll_interval = 10
            while True:
                ret = bench_proc.poll()
                if ret is not None:
                    reader.join(timeout=2)
                    out.write("".join(stdout_lines))
                    if last_queries > 0:
                        print()  # newline after progress bar
                    break

                while stdout_lines:
                    line = stdout_lines.pop(0)
                    out.write(line)
                    out.flush()
                    stripped = line.strip()
                    if stripped:
                        last_harness_line = stripped
                        print(f"  [guidellm] {stripped}", flush=True)

                queries = last_queries
                if query_progress_file.exists():
                    try:
                        d = json.loads(query_progress_file.read_text())
                        queries = d.get("queries_completed", 0)
                    except Exception:
                        pass
                if queries <= 0:
                    queries = _count_from_kubectl_logs()

                now = time.time()
                if queries > last_queries:
                    last_queries = queries
                    last_updated = now
                    last_wait_report = now
                    _write_progress("benchmark", {
                        "timeout_sec": timeout_sec,
                        "run_dir": str(run_dir),
                        "queries_completed": last_queries,
                        "last_progress": datetime.now().isoformat(),
                    })
                    # Progress bar
                    elapsed = now - bench_start
                    if max_requests > 0 and last_queries > 0:
                        pct = min(last_queries / max_requests, 1.0)
                        bar_width = 30
                        filled = int(bar_width * pct)
                        bar = "█" * filled + "░" * (bar_width - filled)
                        rate = last_queries / elapsed if elapsed > 0 else 0
                        eta = (max_requests - last_queries) / rate if rate > 0 else 0
                        print(f"\r  [{bar}] {last_queries}/{max_requests} requests ({pct*100:.0f}%) | {rate:.1f} req/s | ETA {eta:.0f}s", end="", flush=True)
                    else:
                        print(f"\r  {last_queries} requests | {elapsed:.0f}s elapsed", end="", flush=True)
                elif (now - last_updated) >= min(10, QUERY_STALE_SEC) and (now - last_wait_report) >= 10:
                    last_wait_report = now
                    wait_for = int(now - last_updated)
                    last_line = last_harness_line[:200] if last_harness_line else "(no harness output yet)"
                    print(
                        f"\n  Waiting for benchmark progress: {queries} completed requests, no update for {wait_for}s",
                        flush=True,
                    )
                    print(f"  Last guidellm output: {last_line}", flush=True)
                elif (now - last_updated) >= QUERY_STALE_SEC:
                    if (run_dir / "benchmarks.json").exists():
                        _log_run(run_dir, "Benchmark output found despite stale query count")
                        if last_queries > 0:
                            print()
                        break
                    if last_queries > 0:
                        print()
                    if last_harness_line:
                        print(f"  Last guidellm output before abort: {last_harness_line[:200]}", flush=True)
                    return _cleanup(
                        f"Query count unchanged at {queries} for {QUERY_STALE_SEC}s (no progress)"
                    )

                if _elapsed_since(start) >= timeout_sec:
                    if last_queries > 0:
                        print()
                    return _cleanup(f"Benchmark timed out after {timeout_sec}s")
                if m := _check_abort(start, "benchmark", last_progress=last_updated):
                    return _cleanup(m)

                time.sleep(min(poll_interval, 2))

        r = subprocess.CompletedProcess(bench_proc.args, bench_proc.returncode, None, None)
    except Exception as e:
        return _cleanup(f"Benchmark error: {e}")
    finally:
        for proc in (logs_proc, pf):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    if r.returncode != 0:
        _cleanup()
        return False, f"Benchmark failed (exit {r.returncode}). See {run_dir}/harness_output.txt"

    _write_progress("done", {})
    _log_run(run_dir, "Benchmark complete")

    benchmarks_json = run_dir / "benchmarks.json"
    if not benchmarks_json.exists() and (run_dir / "benchmark.json").exists():
        shutil.copy(run_dir / "benchmark.json", benchmarks_json)

    if (run_dir / "benchmarks.json").exists():
        try:
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_summary.py"), str(run_dir)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    # Clean up pod after successful benchmark
    _cleanup()

    benchmarks_json = run_dir / "benchmarks.json"
    if benchmarks_json.exists():
        try:
            data = json.loads(benchmarks_json.read_text())
            b = data.get("benchmarks", [{}])[0]
            m = b.get("metrics", {})
            return True, _fmt_summary(m)
        except Exception:
            pass
    return True, "Benchmark completed (no metrics extracted)"


def main() -> int:
    parser = argparse.ArgumentParser(description="AI experiment: LLM suggests vLLM changes, deploy and benchmark")
    parser.add_argument("--sweep", "-s", help="Sweep name (use runs from results/sweep-NAME/)")
    parser.add_argument("--allow-model-change", action="store_true", help="Allow agent to try quantized model variants")
    parser.add_argument("--refresh-leaderboard", action="store_true", help="Just write leaderboard.txt to sweep dir and exit")
    args = parser.parse_args()
    allow_model_change = args.allow_model_change

    sweep = (args.sweep or os.environ.get("SWEEP", "")).strip()
    if sweep:
        sweep_dir = RESULTS_DIR / f"sweep-{sweep.lower().replace(' ', '-')}"
        if not sweep_dir.exists():
            print(f"Sweep '{sweep}' not found. Run 'make sweep SWEEP={sweep}' first.")
            return 1
        runs_dir = sweep_dir
        results_txt = sweep_dir / "results.txt"
    else:
        sweep_dir = None
        runs_dir = RUNS_DIR
        results_txt = RESULTS_DIR / "results.txt"

    if args.refresh_leaderboard:
        if not sweep_dir:
            print("--refresh-leaderboard requires --sweep")
            return 1
        _write_leaderboard_to_sweep(sweep_dir)
        print(f"Wrote {sweep_dir / 'leaderboard.txt'}")
        return 0

    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    model = os.environ.get("AI_MODEL", "")
    if provider == "anthropic":
        model = model or "claude-opus-4-6"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY"); return 1
        call_fn = lambda p: _call_anthropic(p, model)
    elif provider == "openai":
        model = model or "gpt-5-codex"
        if not os.environ.get("OPENAI_API_KEY"):
            print("Set OPENAI_API_KEY"); return 1
        call_fn = lambda p: _call_openai(p, model)
    else:
        print("AI_PROVIDER must be 'anthropic' or 'openai'"); return 1

    if not RUNLLM.exists():
        print("runllm submodule not found"); return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = (sweep_dir / ts) if sweep_dir else (RUNS_DIR / f"exp_{ts}")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Agent changes go only in run_dir/runllm. Base = best-runllm (sweep) or RUNLLM.
    experiment_dir = run_dir / "runllm"
    if experiment_dir.exists():
        shutil.rmtree(experiment_dir)
    base_runllm = RUNLLM
    if sweep_dir:
        best_link = sweep_dir / "best-runllm"
        try:
            if best_link.exists():
                resolved = best_link.resolve() if best_link.is_symlink() else best_link
                if resolved.exists() and (resolved / "vllm-qwen.yaml").exists():
                    base_runllm = resolved
        except OSError:
            pass
        if base_runllm == RUNLLM and (sweep_dir / "baseline" / "runllm").exists():
            base_runllm = sweep_dir / "baseline" / "runllm"
    shutil.copytree(base_runllm, experiment_dir, ignore=shutil.ignore_patterns(".git"))

    makefile_content = (base_runllm / "Makefile").read_text()
    vllm_content = (base_runllm / "vllm-qwen.yaml").read_text()
    runs_for_context = sweep_dir or RUNS_DIR
    leaderboard = _get_experiment_leaderboard(runs_for_context, PROJECT_ROOT)
    if sweep_dir:
        _write_leaderboard_to_sweep(sweep_dir)
    workload = _get_workload_description(runs_for_context)
    retros_section = _get_retros(runs_for_context)
    retro_bullets = ""
    if retros_section:
        retro_bullets = f"\n**Lessons from failed runs (avoid these):**\n{retros_section[:2000]}\n"

    # Read optimization goal from sweep metadata
    goal = "Minimize latency and maximize throughput (tok/s)."
    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            if sm.get("goal"):
                goal = sm["goal"]
        except Exception:
            pass

    model_change_section = ""
    if allow_model_change:
        model_change_section = """
## Model variants (ALLOW_MODEL_CHANGE=1 is set)

You MAY change the `--model` to a quantized variant of the same model family. This can significantly reduce memory usage and improve throughput/latency. Options:
- `Qwen/Qwen2.5-1.5B-Instruct` (current, FP16/BF16 baseline)
- `Qwen/Qwen2.5-1.5B-Instruct-AWQ` (4-bit AWQ, use `--dtype half --quantization awq`)
- `Qwen/Qwen2.5-1.5B-Instruct-GPTQ-Int4` (4-bit GPTQ, use `--quantization gptq`)
- `Qwen/Qwen2.5-1.5B-Instruct-GPTQ-Int8` (8-bit GPTQ, use `--quantization gptq`)
- `Qwen/Qwen2.5-0.5B-Instruct` (smaller model, much faster but lower quality)
- `Qwen/Qwen2.5-3B-Instruct` (larger model, higher quality but slower)

When changing the model, also update the Makefile's `VLLM_MODEL` variable to match, and return the Makefile in a ```makefile block```.
Do NOT change to a completely different model family—stay within Qwen2.5.
"""

    prompt = f"""You are optimizing vLLM inference on Kubernetes (H200 GPU, CoreWeave).

**Hardware:** 1x NVIDIA H200 GPU, node pool: lukas-4h200-pool
**Benchmark workload:** {workload}
**Goal:** {goal}

## Current best config (your baseline to improve on)

```yaml
{vllm_content}
```

## Experiment leaderboard

{leaderboard}
{retro_bullets}
## Hard constraints (DO NOT violate)

- YAML must be `apiVersion: v1, kind: Pod` with `metadata.name: vllm-qwen`
- Do NOT use Deployments, ReplicaSets, or change the pod name
- Do NOT add startup/readiness/liveness probes (the harness handles health checks)
- Do NOT set `--host` or `--port` (defaults work)
- Do NOT change `restartPolicy` from `Always`
- Image MUST be `vllm/vllm-openai:nightly` (do not change the image tag)
- Do NOT change the container entrypoint/command. Use the default entrypoint with `args:` containing `"--model"`, `"ModelName"`, and flags. Do NOT use `command: ["vllm"]` with `args: ["serve", ...]`, do NOT use `python3 -m vllm.entrypoints.openai.api_server`. The default entrypoint in the image already handles serving.
- Do NOT use `--disable-log-requests` or `--num-scheduler-steps` (not recognized in nightly). Use `--disable-log-stats` for logging.
{"- Do NOT change the --model (model changes not enabled for this sweep)" if not allow_model_change else ""}
{model_change_section}
## Observed quirks in this image / harness

- Base your diagnosis on the leaderboard, workload, and provided logs. Do not invent root causes that are not supported by evidence.
- If a retry shows many successful `POST /v1/chat/completions` lines in the logs, treat that as evidence the server is making benchmark progress. That is more likely a harness/watchdog issue than a serving/config failure.
- `VLLM_ATTENTION_BACKEND` has produced `Unknown vLLM environment variable` warnings in this image. Do NOT introduce it if it is absent. If it is already present in the current best config, only change it as its own dedicated experiment.
- `--performance-mode` has previously failed in this image. Do NOT introduce it unless it already appears in a successful leaderboard run.

## vLLM serve args reference (from vLLM docs, performance-relevant subset)

**Model & precision:**
- `--model` — HuggingFace model name/path
- `--dtype` — auto|half|bfloat16|float16 (default: auto). "half" recommended for AWQ quantization.
- `--quantization, -q` — awq, gptq, fp8, or None (inferred from model config if not set)
- `--max-model-len` — Model context length. Use -1 or "auto" for auto-detection.
- `--enforce-eager` — Disables CUDA graphs, uses eager-mode PyTorch. Can reduce TTFT but may hurt throughput.

**GPU & memory:**
- `--tensor-parallel-size, -tp` — Number of TP groups (default: 1)
- `--gpu-memory-utilization` — Fraction of GPU memory for model (0-1, default: 0.9)
- `--kv-cache-dtype` — auto|fp8|fp8_e4m3|bfloat16 (default: auto). fp8 reduces KV cache memory ~50%.
- `--block-size` — KV cache block size in tokens (default: auto)

**Scheduling & batching:**
- `--max-num-batched-tokens` — Max tokens per iteration (controls prefill chunk size)
- `--max-num-seqs` — Max sequences per iteration (controls concurrent request capacity)
- `--enable-chunked-prefill` — Allow chunking long prefills across iterations
- `--max-num-partial-prefills` — Max concurrent partial prefills (default: 1)
- `--async-scheduling` — Async scheduling to avoid GPU idle gaps

**Caching:**
- `--enable-prefix-caching` — Cache common prefix KV blocks across requests

**Speculative decoding (high-impact for latency):**
- `--speculative-config` — JSON config. Example: `--speculative-config '{{"model": "Qwen/Qwen2.5-0.5B-Instruct", "num_speculative_tokens": 5}}'`
- Uses a smaller draft model to predict tokens verified by the main model. Can significantly reduce TTFT and per-request latency.
- The draft model must be compatible (same tokenizer family). For Qwen2.5-1.5B, use Qwen2.5-0.5B as draft.
- In YAML args, pass as: `- "--speculative-config"` followed by `- '{{"model": "Qwen/Qwen2.5-0.5B-Instruct", "num_speculative_tokens": 5}}'`

**Compilation & CUDA graphs (high-impact for latency):**
- `--compilation-config, -cc` — torch.compile and CUDA graph settings. Pass as JSON string.
  - `mode`: 0=no compile, 1=inductor, 2=inductor+reduce-overhead, 3=max-autotune (slowest startup, best perf)
  - Example: `--compilation-config '{{"mode": 3}}'`
  - In YAML: `- "--compilation-config"` followed by `- '{{"mode": 3}}'`
- `--performance-mode` — balanced|interactivity|throughput (default: balanced)
  - "interactivity": optimizes for low per-request latency (fine-grained CUDA graphs)
  - "throughput": optimizes for aggregate tok/s (larger CUDA graphs, more batching)

**Environment variables (set in pod env):**
You can add env vars to `spec.containers[0].env` to tune vLLM behavior:
- `VLLM_ATTENTION_BACKEND` — Override attention backend (e.g. "FLASH_ATTN", "FLASHINFER")
- `VLLM_USE_TRITON_FLASH_ATTN` — "1" to force Triton flash attention
- `CUDA_VISIBLE_DEVICES` — GPU selection (default: all)
- `VLLM_WORKER_MULTIPROC_METHOD` — "spawn" or "fork" for worker processes
- `VLLM_LOGGING_LEVEL` — "WARNING" to reduce log overhead
Example in YAML:
```
env:
  - name: VLLM_ATTENTION_BACKEND
    value: "FLASHINFER"
  - name: VLLM_LOGGING_LEVEL
    value: "WARNING"
```

**Other tuning:**
- `--optimization-level` — 0-3 (default: 2). Higher = better perf, slower startup.
- `--attention-backend` — Override attention backend via CLI (alternative to env var)
- `--load-format` — auto|safetensors|tensorizer (default: auto). "tensorizer" for fast CoreWeave loading.
- `--disable-log-stats` — Disable periodic stats logging (minor perf gain)
- NOTE: `--disable-log-requests` and `--num-scheduler-steps` do NOT exist in this image.

## Your task

**IMPORTANT:** Review the leaderboard above. Do NOT repeat a strategy that already failed or that produced worse results than the current best. Try something genuinely different.

Use a search mindset: each run should help the sweep learn what works, not just make a large grab-bag of edits.
- Default to exactly one meaningful change relative to the current best config.
- Only change multiple knobs together when you have a specific hypothesis that they interact and should be tested as a bundle.
- Prefer isolated experiments that make it easy to attribute wins or losses to a single variable.
- If you do bundle changes, explain clearly why those changes need to be tested together.
- Give a small change manifest before the YAML so the exact knob change is explicit.

1. Start with this exact structure:
   - `Experiment type: single-change` or `Experiment type: bundle`
   - `Evidence:` with 1-3 bullets grounded in the leaderboard/workload/logs
   - `Changed knobs:` with one bullet per changed knob in the form `knob: old -> new`
   - `Why:` with 1-2 short bullets
2. Describe a config that is different from the baseline AND from previous attempts shown in the leaderboard.
3. Return the complete vllm-qwen.yaml in a ```yaml block```.
{"3. If you changed the model, also return the Makefile in a ```makefile block``` with updated VLLM_MODEL." if allow_model_change else ""}

**To request a file** from a previous run: respond with `REQUEST_FILE: results/sweep-NAME/TIMESTAMP/FILE` (e.g. deploy.log, kubectl_logs.txt). You'll get the contents and can then provide your YAML."""

    if sweep_dir and (sweep_dir / "sweep_metadata.json").exists():
        try:
            sm = json.loads((sweep_dir / "sweep_metadata.json").read_text())
            benchmark = sm.get("benchmark", "quick")
        except Exception:
            benchmark = "quick"
    else:
        benchmark = os.environ.get("BENCHMARK", "").lower()
        if not benchmark or benchmark not in BENCHMARK_PRESETS:
            benchmark = "quick"
    if benchmark not in BENCHMARK_PRESETS:
        benchmark = "quick"

    max_attempts = 10
    failure_context: dict | None = None
    last_description = ""
    conversation_turns: list[tuple[str, str]] = []

    for attempt in range(max_attempts):
        if attempt > 0 and failure_context:
            result_msg = failure_context.get("result", "")
            # Infrastructure errors (kubectl/K8s) cannot be fixed by changing YAML—exit early
            if _is_infrastructure_error(result_msg):
                print("\n*** Infrastructure error (not fixable by vLLM config) ***")
                print(result_msg[:600])
                print("\nThis is a Kubernetes/kubectl setup issue. Check:")
                print("  1. KUBECONFIG is set and points to your cluster")
                print("  2. kubectl auth can-i delete pods  (must return yes)")
                print("  3. kubectl get pods  (should reach the cluster)")
                _write_conversation(run_dir, conversation_turns, sweep_dir)
                return 1

            # Fix prompt: crash + logs + current config
            deploy_log = failure_context.get("deploy_log", "")[-4000:]
            kubectl_logs = failure_context.get("kubectl_logs", "")[-6000:]
            vllm_cur = (experiment_dir / "vllm-qwen.yaml").read_text()
            makefile_cur = (experiment_dir / "Makefile").read_text()
            prompt = f"""Attempt {attempt} FAILED. Diagnose whether this is actually a config problem before changing anything.

**Failure:** {result_msg}

**deploy.log (last 4k):**
```
{deploy_log}
```

**kubectl logs (last 6k):**
```
{kubectl_logs}
```

**Failed vllm-qwen.yaml:**
```yaml
{vllm_cur[:2500]}
```

**Fix rules:**
- Base your diagnosis on the provided logs and benchmark behavior, not generic vLLM heuristics.
- If the evidence suggests this is a harness/watchdog issue rather than a serving/config issue (for example, many successful `POST /v1/chat/completions` lines), you may respond with `NO_CONFIG_CHANGE: <reason>` and do not return YAML.
- Otherwise, keep the fix minimal and targeted.
- Change exactly one knob unless the YAML is invalid or multiple settings are inseparable.
- Preserve all other args/env/image/resources lines byte-for-byte.
- First consider reverting the most recent knob change before inventing a new hypothesis.
- Keep Pod kind, name=vllm-qwen. Image must stay vllm/vllm-openai:nightly.
- Do NOT change the container entrypoint. No `command:` field. Use `args:` with `--model` as a flag.
- Do NOT use `--disable-log-requests` (does not exist). Use `--disable-log-stats` instead.
- If --kv-cache-dtype fp8 fails, set --dtype bfloat16.
- Do NOT introduce `VLLM_ATTENTION_BACKEND` if it is absent. Do NOT introduce `--performance-mode`.

If you are changing config, start with this exact structure before the YAML:
- `Experiment type: single-change` or `Experiment type: bundle`
- `Evidence:` with 1-3 bullets grounded in the logs
- `Changed knobs:` with one bullet per changed knob in the form `knob: old -> new`
- `Why:` with 1-2 short bullets

If you return YAML, it must be the complete corrected config in a ```yaml block```."""
            current_prompt = prompt
            print(f"Retry {attempt + 1}/{max_attempts}: asking agent to fix crash...")
        else:
            current_prompt = prompt

        _write_progress("llm_call", {"experiment_dir": str(experiment_dir), "attempt": attempt + 1})
        max_file_rounds = 3 if attempt == 0 else 1  # Allow REQUEST_FILE only on first attempt
        call_prompt = current_prompt
        response = ""
        req_path = ""
        file_content = ""
        for round_num in range(max_file_rounds + 1):
            if round_num > 0:
                call_prompt = f"{call_prompt}\n\n**File you requested ({req_path}):**\n```\n{file_content}\n```\n\nNow provide your YAML suggestion (modified vllm-qwen.yaml and optionally Makefile), or `NO_CONFIG_CHANGE: <reason>` if the evidence shows the config should stay the same."
            print(f"Calling {provider} ({model})..." + (f" [round {round_num + 1}, after file read]" if round_num > 0 else "") + (f" (attempt {attempt + 1}/{max_attempts})" if attempt > 0 else ""))
            try:
                response = call_fn(call_prompt)
            except Exception as e:
                print(f"LLM error: {e}")
                conversation_turns.append((call_prompt, f"[LLM error: {e}]"))
                _write_conversation(run_dir, conversation_turns, sweep_dir)
                _append_result(experiment_dir, f"LLM error: {e}", "", results_path=results_txt)
                return 1
            conversation_turns.append((call_prompt, response))
            _write_conversation(run_dir, conversation_turns, sweep_dir)
            req_match = re.search(r"REQUEST_FILE:\s*([^\s\n]+)", response)
            if not req_match or round_num >= max_file_rounds:
                break
            req_path = req_match.group(1).strip()
            fp = (PROJECT_ROOT / req_path).resolve()
            if not str(fp).startswith(str(PROJECT_ROOT.resolve())):
                response = response.replace(req_match.group(0), f"[Path {req_path} denied: outside project]")
                break
            try:
                rel = str(fp.relative_to(PROJECT_ROOT))
            except ValueError:
                response = response.replace(req_match.group(0), "[Path outside project]")
                break
            if not rel.startswith("results"):
                response = response.replace(req_match.group(0), "[Path must be under results/]")
                break
            if not fp.exists():
                response = response.replace(req_match.group(0), f"[File not found: {req_path}]")
                break
            if fp.is_dir():
                try:
                    children = list(fp.iterdir())
                    file_content = "Directory contents:\n" + "\n".join(f.name for f in sorted(children)[:50])
                    if len(children) > 50:
                        file_content += "\n... (and more)"
                except Exception:
                    file_content = "(read error)"
            else:
                try:
                    raw = fp.read_text(errors="replace")
                    file_content = raw[:50000] + ("\n... (truncated)" if len(raw) > 50000 else "")
                except Exception as e:
                    file_content = f"(read error: {e})"
            print(f"Read {req_path} ({len(file_content)} chars)")

        no_config_change_reason = _extract_no_config_change_reason(response)
        yaml_content = _extract_yaml(response)
        if no_config_change_reason and not yaml_content:
            yaml_content = (experiment_dir / "vllm-qwen.yaml").read_text()
        if not yaml_content:
            # Retry once: agent may have returned prose instead of YAML block
            retry_prompt = f"""Your previous response did not include a valid result. You must either:
1. return `NO_CONFIG_CHANGE: <reason>` if the logs show the config should stay the same, or
2. return the complete Kubernetes Pod YAML in a ```yaml block```.

**Failure we're fixing:** {(failure_context or {}).get("result", "unknown")[:300]}

**Current config (return this or a fixed version in ```yaml ... ```):**
```yaml
{(experiment_dir / "vllm-qwen.yaml").read_text()[:2000]}
```

Return either `NO_CONFIG_CHANGE: <reason>` or the fixed vllm-qwen.yaml in a ```yaml block```. If you didn't change it, return it unchanged."""
            print("Could not extract YAML—asking agent to retry with explicit format...")
            try:
                retry_response = call_fn(retry_prompt)
                conversation_turns.append((retry_prompt, retry_response))
                no_config_change_reason = _extract_no_config_change_reason(retry_response)
                yaml_content = _extract_yaml(retry_response)
                if no_config_change_reason and not yaml_content:
                    yaml_content = (experiment_dir / "vllm-qwen.yaml").read_text()
            except Exception as e:
                print(f"Retry failed: {e}")
            if not yaml_content:
                description = _extract_description(response)
                err = "Could not extract YAML from agent response (after retry)"
                print(err)
                _write_conversation(run_dir, conversation_turns, sweep_dir)
                _append_result(experiment_dir, description, err, results_path=results_txt)
                return 1
            response = retry_response  # use for description extraction

        # Validate: if model changes not allowed, revert any model change in the YAML
        if not allow_model_change:
            baseline_model_m = re.search(r'"--model"\s*\n\s*-\s*"([^"]+)"', vllm_content)
            proposed_model_m = re.search(r'"--model"\s*\n\s*-\s*"([^"]+)"', yaml_content)
            if baseline_model_m and proposed_model_m:
                baseline_model = baseline_model_m.group(1)
                proposed_model = proposed_model_m.group(1)
                if proposed_model != baseline_model:
                    print(f"Agent tried to change model to {proposed_model} — reverting to {baseline_model}")
                    yaml_content = yaml_content.replace(proposed_model, baseline_model)

        # Ask agent for a concise summary (for terminal/metadata); fallback to parsed description
        if no_config_change_reason:
            description = f"No config change: {no_config_change_reason}"
        else:
            summary = _ask_agent_summary(response, call_fn)
            description = summary if summary else _extract_description(response)
        last_description = description

        makefile_content_new = _extract_makefile(response) or (makefile_content if attempt == 0 else (experiment_dir / "Makefile").read_text())
        (experiment_dir / "vllm-qwen.yaml").write_text(yaml_content)
        (experiment_dir / "Makefile").write_text(makefile_content_new)

        shutil.copy(experiment_dir / "vllm-qwen.yaml", run_dir / "vllm_config.yaml")
        (run_dir / "run_metadata.json").write_text(json.dumps({
            "timestamp": ts,
            "description": description[:500],
            "experiment_dir": str(experiment_dir),
            "benchmark": benchmark,
            "sweep": sweep or None,
            "attempt": attempt + 1,
        }, indent=2))

        print(f"Run dir: {run_dir} (modified runllm in run_dir/runllm/)")
        print()
        print("━" * 60)
        print("AGENT IMPROVEMENT STRATEGY")
        print("━" * 60)
        print()
        print(description)
        print()
        print(f"Attempt {attempt + 1}/{max_attempts}  |  Benchmark: {benchmark}" + (" (from sweep)" if sweep_dir else ""))
        print("━" * 60)
        print()
        print("Deploying and running benchmark...")

        success, result = _deploy_and_benchmark(experiment_dir, benchmark, run_dir, ts, sweep=sweep or None)
        _append_result(experiment_dir, description, result, success=success, run_dir=run_dir, results_path=results_txt)

        if success:
            _write_conversation(run_dir, conversation_turns, sweep_dir)
            if sweep_dir:
                from sweep_utils import update_best_runllm
                update_best_runllm(sweep_dir, RUNLLM)
                _write_leaderboard_to_sweep(sweep_dir)
            print(f"Results: {result}")
            return 0

        # Gather failure context for retry
        deploy_log = ""
        kubectl_logs = ""
        if (run_dir / "deploy.log").exists():
            deploy_log = (run_dir / "deploy.log").read_text(errors="replace")
        if (run_dir / "kubectl_logs.txt").exists():
            kubectl_logs = (run_dir / "kubectl_logs.txt").read_text(errors="replace")
        failure_context = {"result": result, "deploy_log": deploy_log, "kubectl_logs": kubectl_logs}
        print(f"Attempt {attempt + 1} failed: {result[:200]}...")

    # Exhausted retries: ask agent to write retro
    print("All 10 attempts failed. Asking agent to write retrospective...")
    retro_prompt = f"""The vLLM optimization run failed after 10 attempts. Write a retrospective for future AI agents to learn from.

**Run directory:** {run_dir}
**Last description:** {last_description}
**Final failure:** {failure_context.get("result", "")}

**deploy.log (last 6k):**
```
{(failure_context.get("deploy_log", ""))[-6000:]}
```

**kubectl_logs.txt (last 8k):**
```
{(failure_context.get("kubectl_logs", ""))[-8000:]}
```

**Final vllm-qwen.yaml that was used:**
```yaml
{(experiment_dir / "vllm-qwen.yaml").read_text()[:3000]}
```

Write a RETRO.md document (in markdown) that will be saved to the run directory and shown to future agents. Include:
1. What went wrong (root cause if identifiable)
2. What was tried across the 10 attempts
3. Concrete recommendations for future agents (what to try, what to avoid)
4. Any vLLM/configuration insights

Return the retrospective in a ```markdown block```."""

    try:
        retro_response = call_fn(retro_prompt)
    except Exception as e:
        retro_response = f"# Retrospective\n\nFailed to generate: {e}"
    conversation_turns.append((retro_prompt, retro_response))
    _write_conversation(run_dir, conversation_turns, sweep_dir)
    retro_content = _extract_code_block(retro_response, "markdown") or retro_response
    if retro_content:
        (run_dir / "RETRO.md").write_text(retro_content)
        print(f"Saved RETRO.md to {run_dir}")
    _append_result(experiment_dir, last_description, f"Failed after 10 attempts. Retro saved. Last error: {failure_context.get('result', '')}", success=False, run_dir=run_dir, results_path=results_txt)
    if sweep_dir:
        if (run_dir / "run_metadata.json").exists():
            try:
                rm = json.loads((run_dir / "run_metadata.json").read_text())
                rm["result"] = failure_context.get("result", "")[:500]
                (run_dir / "run_metadata.json").write_text(json.dumps(rm, indent=2))
            except Exception:
                pass
        _write_leaderboard_to_sweep(sweep_dir)
    print(f"Results: Failed after 10 attempts. See {run_dir}/RETRO.md")
    return 1


def _write_conversation(run_dir: Path, turns: list[tuple[str, str]], sweep_dir: Path | None = None) -> None:
    """Save full agent conversation to run_dir/agent.log. If sweep_dir, also append to sweep_dir/agent.log."""
    lines = []
    for i, (prompt, response) in enumerate(turns, 1):
        lines.append(f"\n{'='*60}\nTURN {i} - USER (prompt)\n{'='*60}\n\n{prompt}")
        lines.append(f"\n{'='*60}\nTURN {i} - ASSISTANT (response)\n{'='*60}\n\n{response}")
    content = "\n".join(lines).lstrip() if lines else "(no conversation)"
    (run_dir / "agent.log").write_text(content, encoding="utf-8")
    if sweep_dir:
        sweep_log = sweep_dir / "agent.log"
        header = f"\n\n{'#'*70}\n# Run {run_dir.name} ({datetime.now().isoformat()})\n{'#'*70}\n"
        with open(sweep_log, "a", encoding="utf-8") as f:
            f.write(header)
            f.write(content)


def _append_result(experiment_dir: Path, description: str, result: str, success: bool = True, run_dir: Path | None = None, results_path: Path | None = None) -> None:
    path = results_path or (RESULTS_DIR / "results.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 60 + "\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Experiment directory: {experiment_dir}\n")
        if run_dir:
            f.write(f"Run directory (logs): {run_dir}\n")
        f.write(f"Summary: {description[:500]}\n")
        f.write(f"Success: {success}\n")
        f.write(f"Results: {result}\n")
        f.write("=" * 60 + "\n")


if __name__ == "__main__":
    sys.exit(main())
