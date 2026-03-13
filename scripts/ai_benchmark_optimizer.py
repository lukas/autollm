#!/usr/bin/env python3
"""
AI-driven vLLM optimization: run baseline, get AI suggestion, apply, benchmark, compare.

Requires: ANTHROPIC_API_KEY or OPENAI_API_KEY. Uses VLLM_CONFIG (default: runllm/qwen2.5-1.5b/vllm-config.yaml).

Usage:
  ANTHROPIC_API_KEY=xxx make ai-benchmark-optimize
  VLLM_CONFIG=runllm/qwen2.5-1.5b/vllm-config.yaml make ai-optimize
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_VLLM = PROJECT_ROOT / "runllm" / "qwen2.5-1.5b" / "vllm-config.yaml"
VLLM_YAML = Path(os.environ.get("VLLM_CONFIG", str(_DEFAULT_VLLM))).resolve()
RESULTS_DIR = PROJECT_ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"
STATE_FILE = RESULTS_DIR / "ai_optimizer_state.json"
API_EXCHANGE_FILE = RESULTS_DIR / "ai_api_exchange.json"


def _setup_log_file() -> None:
    log_path = os.environ.get("AI_OPTIMIZER_LOG")
    if not log_path:
        return
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        class Tee:
            def __init__(self, stream, log):
                self._stream, self._log = stream, log
            def write(self, data):
                self._stream.write(data); self._stream.flush()
                self._log.write(data); self._log.flush()
            def flush(self):
                self._stream.flush(); self._log.flush()
        sys.stdout = Tee(sys.__stdout__, log_file)  # type: ignore
        sys.stderr = Tee(sys.__stderr__, log_file)  # type: ignore
    except OSError:
        pass


def _metric(m: dict, k: str, sub: str = "successful") -> float | None:
    o = m.get(k, {})
    suc = o.get(sub) if isinstance(o, dict) else {}
    return suc.get("mean") if isinstance(suc, dict) else None


def _fmt_summary(m: dict) -> str:
    lat = _metric(m, "request_latency")
    ttft = _metric(m, "time_to_first_token_ms")
    itl = _metric(m, "inter_token_latency_ms")
    tok = _metric(m, "tokens_per_second")
    rps = _metric(m, "requests_per_second")
    parts = []
    if lat is not None: parts.append(f"Latency: {lat*1000:.0f}ms")
    if ttft is not None: parts.append(f"TTFT: {ttft:.0f}ms")
    if itl is not None: parts.append(f"ITL: {itl:.2f}ms")
    if tok is not None: parts.append(f"Throughput: {tok:.0f} tok/s")
    if rps is not None: parts.append(f"Req/s: {rps:.1f}")
    return " | ".join(parts) if parts else "—"


def _get_latest_benchmark() -> tuple[dict | None, str | None, Path | None]:
    def _load(d: Path) -> tuple[dict, str, Path]:
        with open(d / "benchmarks.json") as f:
            data = json.load(f)
        b = data.get("benchmarks", [{}])[0]
        m = b.get("metrics", {})
        return data, _fmt_summary(m), d

    if RUNS_DIR.exists():
        runs = sorted(
            [d for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "benchmarks.json").exists()],
            key=lambda d: d.name, reverse=True,
        )
        if runs:
            return _load(runs[0])

    fp = RESULTS_DIR / "benchmarks.json"
    if fp.exists():
        with open(fp) as f:
            data = json.load(f)
        b = data.get("benchmarks", [{}])[0]
        m = b.get("metrics", {})
        return data, _fmt_summary(m), None
    return None, None, None


def _call_claude(prompt: str, model: str = "claude-opus-4-6") -> str:
    from anthropic import Anthropic
    msg = Anthropic().messages.create(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text if msg.content else ""


def _call_openai(prompt: str, model: str = "gpt-5.4") -> str:
    from openai import OpenAI
    client = OpenAI()
    if "codex" in model.lower():
        r = client.responses.create(model=model, max_output_tokens=4096, input=[{"role": "user", "content": prompt}])
        return r.output_text if hasattr(r, "output_text") and r.output_text else ""
    r = client.chat.completions.create(model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content if r.choices else ""


def _extract_strategy(text: str) -> str:
    m = re.search(r"Strategy:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _config_diff_summary(old_yaml: str, new_yaml: str) -> str:
    try:
        import yaml
        old_spec = yaml.safe_load(old_yaml)
        new_spec = yaml.safe_load(new_yaml)
        old_args = (old_spec.get("spec", {}) or {}).get("containers", [{}])[0].get("args") or []
        new_args = (new_spec.get("spec", {}) or {}).get("containers", [{}])[0].get("args") or []
        if old_args != new_args:
            return f"args: {len(new_args)} (was {len(old_args)})"
        return "model or resources"
    except Exception:
        return "config changed"


def _ask_llm_for_fix(error_type: str, error_detail: str, config: str, provider: str, model: str, call_fn) -> str:
    prompt = f"""An error occurred while running the vLLM optimization benchmark:

**Error:** {error_type}
**Details:** {error_detail}

**Current vllm config:**
```yaml
{config}
```

**Your task:** Suggest how to fix this. Be specific and actionable (2-4 sentences)."""
    try:
        return call_fn(prompt)
    except Exception as e:
        return f"(Could not reach LLM: {e})"


def _read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"history": []}


def _write_state(state: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _extract_yaml(text: str) -> str | None:
    m = re.search(r"```(?:yaml|yml)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if m:
        s = m.group(1).strip()
        if "apiVersion:" in s and ("vllm" in s.lower() or "kind:" in s):
            return s
    return None


def main() -> None:
    _setup_log_file()

    parser = argparse.ArgumentParser(description="AI-driven vLLM optimization")
    parser.add_argument("--skip-pod-restart", action="store_true", help="Do not restart vLLM pod")
    parser.add_argument("--benchmark", choices=["fast", "full"], default=os.environ.get("BENCHMARK_MODE", "fast"))
    args = parser.parse_args()
    fast_benchmark = args.benchmark == "fast"

    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    model = os.environ.get("AI_MODEL", "")
    if provider == "anthropic":
        model = model or "claude-opus-4-6"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY"); sys.exit(1)
        call_fn = lambda p: _call_claude(p, model)
    elif provider == "openai":
        model = model or "gpt-5.4"
        if not os.environ.get("OPENAI_API_KEY"):
            print("Set OPENAI_API_KEY"); sys.exit(1)
        call_fn = lambda p: _call_openai(p, model)
    else:
        print("AI_PROVIDER must be 'anthropic' or 'openai'"); sys.exit(1)

    if not VLLM_YAML.exists():
        print(f"VLLM config not found: {VLLM_YAML}. Set VLLM_CONFIG or ensure runllm/<model>/vllm-config.yaml exists.")
        sys.exit(1)

    config = VLLM_YAML.read_text()
    state = _read_state()
    state["current_run"] = {
        "status": "starting", "step": "Initializing", "provider": provider, "model": model,
        "started_at": datetime.now().isoformat(),
    }
    _write_state(state)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    API_EXCHANGE_FILE.write_text(json.dumps({"request": None, "response": None, "message": "Optimizer starting"}, indent=2))

    print("AI Benchmark Optimizer started", flush=True)
    print(f"Provider: {provider}, Model: {model}", flush=True)
    print(f"VLLM config: {VLLM_YAML}", flush=True)
    print(f"Benchmark: {'fast (5 req, ~15s)' if fast_benchmark else 'full (200 req, ~10 min)'}", flush=True)

    # Step 1: Baseline benchmark
    state["current_run"].update({"status": "baseline", "step": "Running baseline benchmark..."})
    _write_state(state)
    print("Running baseline benchmark...", flush=True)
    env = os.environ.copy()
    env["VLLM_CONFIG"] = str(VLLM_YAML)
    baseline_cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_harness.py"), "--description", "baseline"]
    if fast_benchmark:
        baseline_cmd.append("--fast")
    r = subprocess.run(baseline_cmd, cwd=str(PROJECT_ROOT), env=env)
    if r.returncode != 0:
        err_detail = "Baseline benchmark failed"
        if RUNS_DIR.exists():
            for d in sorted([x for x in RUNS_DIR.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)[:1]:
                if (d / "run.log").exists():
                    err_detail = (d / "run.log").read_text(); break
        state["current_run"].update({"status": "error", "step": "Baseline benchmark failed"})
        _write_state(state)
        fix = _ask_llm_for_fix("Baseline benchmark failed", err_detail[-2000:], config, provider, model, call_fn)
        state["current_run"]["fix_suggestion"] = fix
        _write_state(state)
        print("\n--- LLM fix suggestion ---\n", fix, flush=True)
        sys.exit(1)

    bench_data, bench_summary, _ = _get_latest_benchmark()
    if not bench_summary:
        bench_summary = "Baseline run produced no metrics."
    print(f"Baseline metrics: {bench_summary}", flush=True)

    prompt = f"""You are optimizing vLLM inference performance. Modify the vLLM pod configuration to improve benchmark results.

**Current vllm config:**
```yaml
{config}
```

**Latest benchmark results:**
{bench_summary}

**Your task:** Propose a single, concrete modification to improve latency or throughput. Examples: change --max-model-len, --gpu-memory-utilization, add --enforce-eager, change tensor-parallel-size.

Format your response as:
1. A single line: Strategy: <brief description>
2. The complete modified YAML in a ```yaml code block```

Preserve apiVersion, kind, metadata, spec structure."""

    state["current_run"].update({"status": "calling_ai", "step": f"Calling {provider} ({model})..."})
    _write_state(state)
    API_EXCHANGE_FILE.write_text(json.dumps({"request": {"provider": provider, "model": model, "prompt": prompt}, "response": None}, indent=2))

    print(f"Calling {provider} ({model})...")
    response = call_fn(prompt)
    try:
        exchange = json.loads(API_EXCHANGE_FILE.read_text())
    except Exception:
        exchange = {"request": {}, "response": None}
    exchange["response"] = {"raw": response}
    API_EXCHANGE_FILE.write_text(json.dumps(exchange, indent=2))

    strategy = _extract_strategy(response)
    yaml_content = _extract_yaml(response)
    if not yaml_content:
        state["current_run"].update({"status": "error", "step": "Failed to extract YAML"})
        _write_state(state)
        print("Could not extract YAML. Raw:", response[:2000])
        sys.exit(1)

    changes_summary = _config_diff_summary(config, yaml_content)
    state["current_run"].update({"strategy": strategy or "", "changes_summary": changes_summary, "status": "applying", "step": f"Applying: {strategy or changes_summary}"})
    _write_state(state)

    backup = VLLM_YAML.with_suffix(".yaml.bak")
    backup.write_text(config)
    VLLM_YAML.write_text(yaml_content)
    print(f"Applied. Backup at {backup}")

    import yaml as _yaml
    try:
        _doc = _yaml.safe_load(yaml_content)
        _pod_name = _doc.get("metadata", {}).get("name", "vllm")
    except Exception:
        _pod_name = "vllm"

    # Restart pod
    state["current_run"].update({"status": "restarting_pod", "step": "Restarting vLLM pod..."})
    _write_state(state)
    if not args.skip_pod_restart:
        print("Restarting vLLM pod...")
        for cmd, err_msg in [
            (["kubectl", "delete", "pod", _pod_name, "--ignore-not-found=true"], "kubectl delete failed"),
            (["kubectl", "apply", "-f", str(VLLM_YAML)], "kubectl apply failed"),
            (["kubectl", "wait", "--for=condition=Ready", f"pod/{_pod_name}", "--timeout=300s"], "Pod did not become Ready"),
        ]:
            rr = subprocess.run(cmd, capture_output=True, text=True)
            if rr.returncode != 0:
                err = (rr.stderr or rr.stdout or "unknown").strip()
                state["current_run"].update({"status": "error", "step": err_msg})
                _write_state(state)
                fix = _ask_llm_for_fix(err_msg, err, yaml_content, provider, model, call_fn)
                state["current_run"]["fix_suggestion"] = fix
                _write_state(state)
                VLLM_YAML.write_text(config)
                sys.exit(1)
        time.sleep(60)
        print("Pod ready.")

    # Run optimization benchmark
    state["current_run"].update({"status": "benchmarking", "step": "Running benchmark..."})
    _write_state(state)
    opt_cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "benchmark_harness.py"), "--description", f"AI suggestion ({provider})"]
    if fast_benchmark:
        opt_cmd.append("--fast")
    r = subprocess.run(opt_cmd, cwd=str(PROJECT_ROOT), env=env)
    if r.returncode != 0:
        err_detail = "Benchmark failed"
        if RUNS_DIR.exists():
            for d in sorted([x for x in RUNS_DIR.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)[:1]:
                if (d / "run.log").exists():
                    err_detail = (d / "run.log").read_text(); break
        state["current_run"].update({"status": "error", "step": "Benchmark failed"})
        _write_state(state)
        fix = _ask_llm_for_fix("Benchmark failed", err_detail[-2000:], yaml_content, provider, model, call_fn)
        state["current_run"]["fix_suggestion"] = fix
        _write_state(state)
        VLLM_YAML.write_text(config)
        sys.exit(r.returncode)

    _, new_summary, run_dir = _get_latest_benchmark()
    print("\n--- Comparison ---")
    print(f"Before: {bench_summary}")
    print(f"After:  {new_summary}")

    if run_dir:
        (run_dir / "optimizer_metadata.json").write_text(json.dumps({
            "provider": provider, "model": model, "strategy": strategy or "", "changes_summary": changes_summary,
            "before_metrics": bench_summary, "after_metrics": new_summary,
        }, indent=2))

    run_relative = str(run_dir.relative_to(RESULTS_DIR)) if run_dir else None
    state["history"] = state.get("history", []) + [{
        "timestamp": run_dir.name if run_dir else "", "run_path": run_relative, "provider": provider, "model": model,
        "strategy": strategy or "—", "changes_summary": changes_summary, "before_metrics": bench_summary, "after_metrics": new_summary,
    }]
    state["current_run"] = None
    _write_state(state)

    VLLM_YAML.write_text(config)
    print(f"\nConfig restored. Dashboard: make dashboard → http://localhost:8765/")


if __name__ == "__main__":
    main()
