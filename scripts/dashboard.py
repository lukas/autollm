#!/usr/bin/env python3
"""
Streamlit dashboard for autollm sweep results.

Usage:
    streamlit run scripts/dashboard.py
    make dashboard
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_config import BENCHMARK_MAX_REQUESTS
from sweep_utils import (
    completed_request_count,
    is_valid_run,
    metric_mean,
    sweep_objective,
    sweep_ranking_label,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
PROGRESS_FILE = RESULTS_DIR / "experiment_progress.json"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_sweeps() -> list[dict]:
    """Return list of sweep dicts sorted by most-recent run timestamp."""
    sweeps = []
    if not RESULTS_DIR.exists():
        return sweeps
    for d in RESULTS_DIR.iterdir():
        if not d.is_dir() or not d.name.startswith("sweep-"):
            continue
        meta = {}
        mf = d / "sweep_metadata.json"
        if mf.exists():
            try:
                meta = json.loads(mf.read_text())
            except Exception:
                pass
        latest_ts = ""
        for sub in d.iterdir():
            if sub.is_dir() and re.match(r"\d{8}_\d{6}", sub.name):
                if sub.name > latest_ts:
                    latest_ts = sub.name
        sweeps.append({
            "path": d,
            "name": d.name.replace("sweep-", ""),
            "display": d.name,
            "goal": meta.get("goal", ""),
            "benchmark": meta.get("benchmark", ""),
            "created": meta.get("created_at", ""),
            "latest_run": latest_ts,
        })
    sweeps.sort(key=lambda s: s["latest_run"], reverse=True)
    return sweeps


def _metric_pct(m: dict, key: str, pct: str, sub: str = "successful") -> float | None:
    o = m.get(key, {})
    suc = o.get(sub) if isinstance(o, dict) else {}
    if not isinstance(suc, dict):
        return None
    pcts = suc.get("percentiles", {})
    return pcts.get(pct) if isinstance(pcts, dict) else None


def load_runs(sweep_dir: Path) -> list[dict]:
    """Load all runs for a sweep, with parsed metrics."""
    sweep_name = sweep_dir.name.replace("sweep-", "")
    runs = []
    if not sweep_dir.exists():
        return runs
    for d in sweep_dir.iterdir():
        if not d.is_dir() or d.name.startswith(".") or d.name == "best-runllm":
            continue
        meta = {}
        mf = d / "run_metadata.json"
        if mf.exists():
            try:
                meta = json.loads(mf.read_text())
            except Exception:
                pass

        short_name_file = d / "short_name.txt"
        short_name = ""
        if short_name_file.exists():
            try:
                short_name = short_name_file.read_text().strip()
            except Exception:
                pass

        run = {
            "name": d.name,
            "short_name": short_name,
            "path": d,
            "strategy": meta.get("description", ""),
            "attempt": meta.get("attempt", ""),
            "benchmark": meta.get("benchmark", ""),
            "result_msg": meta.get("result", ""),
            "status": "failed",
            "latency": None,
            "ttft": None,
            "throughput": None,
            "req_s": None,
            "lat_p95": None,
            "ttft_p95": None,
            "completed": None,
            "preemptions": None,
            "gpu_cache": None,
            "score": None,
        }

        bf = d / "benchmarks.json"
        if bf.exists():
            try:
                data = json.loads(bf.read_text())
                if is_valid_run(d, data):
                    benchmarks = data.get("benchmarks") or []
                    if benchmarks:
                        m = benchmarks[0].get("metrics", {})
                        lat = metric_mean(m, "request_latency")
                        ttft = metric_mean(m, "time_to_first_token_ms")
                        tok = metric_mean(m, "tokens_per_second")
                        rps = metric_mean(m, "requests_per_second")
                        run["latency"] = round(lat * 1000) if lat else None
                        run["ttft"] = round(ttft) if ttft else None
                        run["throughput"] = round(tok) if tok else None
                        run["req_s"] = round(rps, 1) if rps else None
                        run["lat_p95"] = round(_metric_pct(m, "request_latency", "p95") * 1000) if _metric_pct(m, "request_latency", "p95") else None
                        run["ttft_p95"] = round(_metric_pct(m, "time_to_first_token_ms", "p95")) if _metric_pct(m, "time_to_first_token_ms", "p95") else None
                        totals = m.get("request_totals", {})
                        run["completed"] = totals.get("successful", completed_request_count(data))
                        run["status"] = "success"

                        obj = sweep_objective(sweep_name)
                        if obj == "throughput" and tok:
                            run["score"] = tok
                        elif obj == "latency" and lat:
                            run["score"] = -lat
                        elif obj == "ttft" and ttft:
                            run["score"] = -ttft
                        elif tok and lat:
                            run["score"] = tok - lat * 100
                else:
                    run["result_msg"] = f"insufficient traffic: {completed_request_count(data)} requests"
            except Exception:
                pass

        vms = d / "vllm_metrics_summary.json"
        if vms.exists():
            try:
                vs = json.loads(vms.read_text())
                p = vs.get("vllm:num_preemptions_total")
                if p is not None:
                    run["preemptions"] = int(p)
                gc = vs.get("vllm:gpu_cache_usage_perc")
                if gc is not None:
                    run["gpu_cache"] = round(gc * 100, 1)
            except Exception:
                pass

        runs.append(run)

    objective = sweep_objective(sweep_name)
    successes = [r for r in runs if r["status"] == "success"]
    failures = [r for r in runs if r["status"] != "success"]

    if objective == "throughput":
        successes.sort(key=lambda r: (-(r["throughput"] or 0), r["latency"] or 999))
    elif objective == "ttft":
        successes.sort(key=lambda r: r["ttft"] or 999999)
    else:
        successes.sort(key=lambda r: r["latency"] or 999)

    failures.sort(key=lambda r: r["name"], reverse=True)
    return successes + failures


def detect_live_run() -> dict | None:
    """Check experiment_progress.json for a live run."""
    if not PROGRESS_FILE.exists():
        return None
    try:
        data = json.loads(PROGRESS_FILE.read_text())
        pid = data.get("pid")
        phase = data.get("phase", "")
        if not pid or phase in ("done", "aborted"):
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return data
    except Exception:
        return None


def _read_file(path: Path, tail: int = 0) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(errors="replace")
        if tail > 0:
            lines = text.splitlines()
            return "\n".join(lines[-tail:])
        return text
    except Exception:
        return ""


def _parse_agent_log(text: str) -> list[dict]:
    """Parse agent.log into turns: [{role, content}, ...]."""
    turns: list[dict] = []
    current_role = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        header = re.match(r"^={10,}\s*$", line)
        turn_header = re.match(r"^TURN\s+\d+\s*-\s*(USER|ASSISTANT)", line, re.IGNORECASE)

        if turn_header:
            if current_role and current_lines:
                turns.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            current_role = turn_header.group(1).upper()
            current_lines = []
        elif header:
            continue
        else:
            current_lines.append(line)

    if current_role and current_lines:
        turns.append({"role": current_role, "content": "\n".join(current_lines).strip()})

    return turns


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

def render_live_panel(progress: dict, sweep_dir: Path | None):
    """Render the live run status panel."""
    phase = progress.get("phase", "unknown")
    run_dir_str = progress.get("run_dir", "")
    queries = progress.get("queries_completed", 0)
    phase_started = progress.get("phase_started", "")

    elapsed = ""
    if phase_started:
        try:
            started = datetime.fromisoformat(phase_started)
            delta = datetime.now() - started
            elapsed = f"{int(delta.total_seconds())}s"
        except Exception:
            pass

    st.markdown("### :red[Live Run in Progress]")
    cols = st.columns(4)
    cols[0].metric("Phase", phase)
    cols[1].metric("Queries", queries)
    cols[2].metric("Phase Elapsed", elapsed)
    cols[3].metric("PID", progress.get("pid", "?"))

    if run_dir_str:
        run_dir = Path(run_dir_str)
        with st.expander("Terminal Output (live)", expanded=False):
            run_log = _read_file(run_dir / "run.log", tail=30)
            harness = _read_file(run_dir / "harness_output.txt", tail=50)
            combined = ""
            if run_log:
                combined += "=== run.log (last 30 lines) ===\n" + run_log + "\n\n"
            if harness:
                combined += "=== harness_output.txt (last 50 lines) ===\n" + harness
            if combined:
                st.code(combined, language="text")
            else:
                st.info("No output yet.")

        agent_log = run_dir / "agent.log"
        if agent_log.exists():
            with st.expander("Agent Conversation", expanded=False):
                render_agent_conversation(agent_log)

    st.divider()


def _summarize_strategy(strategy: str) -> str:
    """Truncate strategy to a short summary if no short_name available."""
    if not strategy:
        return "—"
    words = strategy.split()
    if len(words) <= 8:
        return strategy
    return " ".join(words[:8]) + "…"


def render_leaderboard(runs: list[dict], sweep_name: str):
    """Render the leaderboard as a proper table with clickable rows."""
    if not runs:
        st.info("No runs found for this sweep.")
        return None

    successes = [r for r in runs if r["status"] == "success"]
    failures = [r for r in runs if r["status"] != "success"]

    selected = None

    if successes:
        st.markdown(f"### Successful Runs ({len(successes)}) — ranked by {sweep_ranking_label(sweep_name)}")

        rows = []
        for i, run in enumerate(successes):
            label = run["short_name"] or _summarize_strategy(run["strategy"])
            rows.append({
                "#": i + 1,
                "Name": label,
                "Latency": f"{run['latency']}ms" if run["latency"] is not None else "—",
                "TTFT": f"{run['ttft']}ms" if run["ttft"] is not None else "—",
                "Tok/s": run["throughput"] if run["throughput"] is not None else "—",
                "Req/s": run["req_s"] if run["req_s"] is not None else "—",
                "p95 Lat": f"{run['lat_p95']}ms" if run["lat_p95"] is not None else "—",
                "p95 TTFT": f"{run['ttft_p95']}ms" if run["ttft_p95"] is not None else "—",
                "Reqs": run["completed"] if run["completed"] is not None else "—",
                "Preempt": run["preemptions"] if run["preemptions"] is not None else "—",
                "GPU$": f"{run['gpu_cache']}%" if run["gpu_cache"] is not None else "—",
                "Run": run["name"],
            })

        df = pd.DataFrame(rows)

        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "#": st.column_config.NumberColumn(width="small"),
                "Name": st.column_config.TextColumn(width="medium"),
                "Run": st.column_config.TextColumn(width="small"),
            },
        )

        sel_rows = event.selection.rows if event and event.selection else []
        if sel_rows:
            idx = sel_rows[0]
            if 0 <= idx < len(successes):
                selected = successes[idx]
                st.session_state["selected_run"] = selected["path"]

    if failures:
        with st.expander(f"Failed runs ({len(failures)})", expanded=False):
            fail_rows = []
            for run in failures:
                label = run["short_name"] or _summarize_strategy(run["strategy"])
                err = run["result_msg"] or "unknown"
                if len(err) > 80:
                    err = err[:77] + "…"
                fail_rows.append({
                    "Name": label,
                    "Error": err,
                    "Run": run["name"],
                })
            df_fail = pd.DataFrame(fail_rows)
            fail_event = st.dataframe(
                df_fail, use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row",
            )
            fail_sel = fail_event.selection.rows if fail_event and fail_event.selection else []
            if fail_sel:
                idx = fail_sel[0]
                if 0 <= idx < len(failures):
                    selected = failures[idx]
                    st.session_state["selected_run"] = selected["path"]

    return selected


def render_run_detail(run_dir: Path):
    """Render detailed view of a single run."""
    st.markdown(f"### Run: `{run_dir.name}`")

    meta = {}
    mf = run_dir / "run_metadata.json"
    if mf.exists():
        try:
            meta = json.loads(mf.read_text())
        except Exception:
            pass

    tab_summary, tab_agent, tab_config, tab_logs, tab_server = st.tabs(
        ["Summary", "Agent Conversation", "Config", "Logs", "Server Metrics"]
    )

    with tab_summary:
        if meta.get("description"):
            st.markdown(f"**Strategy:** {meta['description']}")
        if meta.get("benchmark"):
            st.markdown(f"**Benchmark:** {meta['benchmark']}")
        if meta.get("attempt"):
            st.markdown(f"**Attempt:** {meta['attempt']}")
        if meta.get("result"):
            st.error(f"**Result:** {meta['result']}")

        bf = run_dir / "benchmarks.json"
        if bf.exists():
            try:
                data = json.loads(bf.read_text())
                benchmarks = data.get("benchmarks") or []
                if benchmarks:
                    m = benchmarks[0].get("metrics", {})
                    col1, col2, col3, col4 = st.columns(4)
                    lat = metric_mean(m, "request_latency")
                    ttft_val = metric_mean(m, "time_to_first_token_ms")
                    tok = metric_mean(m, "tokens_per_second")
                    rps = metric_mean(m, "requests_per_second")
                    if lat:
                        col1.metric("Latency (mean)", f"{lat*1000:.0f}ms")
                    if ttft_val:
                        col2.metric("TTFT (mean)", f"{ttft_val:.0f}ms")
                    if tok:
                        col3.metric("Throughput", f"{tok:.0f} tok/s")
                    if rps:
                        col4.metric("Req/s", f"{rps:.1f}")

                    col5, col6, col7, col8 = st.columns(4)
                    lat_p50 = _metric_pct(m, "request_latency", "p50")
                    lat_p95 = _metric_pct(m, "request_latency", "p95")
                    ttft_p50 = _metric_pct(m, "time_to_first_token_ms", "p50")
                    ttft_p95 = _metric_pct(m, "time_to_first_token_ms", "p95")
                    if lat_p50:
                        col5.metric("Latency p50", f"{lat_p50*1000:.0f}ms")
                    if lat_p95:
                        col6.metric("Latency p95", f"{lat_p95*1000:.0f}ms")
                    if ttft_p50:
                        col7.metric("TTFT p50", f"{ttft_p50:.0f}ms")
                    if ttft_p95:
                        col8.metric("TTFT p95", f"{ttft_p95:.0f}ms")

                    totals = m.get("request_totals", {})
                    if totals:
                        st.markdown(
                            f"**Requests:** {totals.get('successful', '?')} completed, "
                            f"{totals.get('errored', 0)} errored, "
                            f"{totals.get('incomplete', 0)} incomplete"
                        )
            except Exception:
                st.warning("Could not parse benchmarks.json")
        else:
            st.info("No benchmark results (benchmarks.json not found)")

    with tab_agent:
        agent_log = run_dir / "agent.log"
        if agent_log.exists():
            render_agent_conversation(agent_log)
        else:
            st.info("No agent.log found for this run.")

    with tab_config:
        config_path = run_dir / "vllm_config.yaml"
        if not config_path.exists():
            config_path = run_dir / "runllm" / "vllm-qwen.yaml"
        if config_path.exists():
            st.code(_read_file(config_path), language="yaml")
        else:
            st.info("No config file found.")

    with tab_logs:
        log_files = [
            ("run.log", "text"),
            ("deploy.log", "text"),
            ("kubectl_logs.txt", "text"),
            ("harness_output.txt", "text"),
        ]
        for fname, lang in log_files:
            fp = run_dir / fname
            if fp.exists():
                with st.expander(fname, expanded=fname == "run.log"):
                    content = _read_file(fp)
                    if len(content) > 50000:
                        content = content[-50000:]
                        st.caption("(truncated to last 50KB)")
                    st.code(content, language=lang)

    with tab_server:
        vms = run_dir / "vllm_metrics_summary.json"
        if vms.exists():
            try:
                vs = json.loads(vms.read_text())
                rows = []
                for k, v in sorted(vs.items()):
                    label = k.replace("vllm:", "")
                    if "usage_perc" in k:
                        rows.append({"Metric": label, "Value": f"{v:.1%}"})
                    elif isinstance(v, float) and v == int(v):
                        rows.append({"Metric": label, "Value": str(int(v))})
                    else:
                        rows.append({"Metric": label, "Value": str(v)})
                st.table(rows)
            except Exception:
                st.warning("Could not parse vllm_metrics_summary.json")
        else:
            raw = run_dir / "vllm_metrics.txt"
            if raw.exists():
                st.code(_read_file(raw, tail=100), language="text")
            else:
                st.info("No server metrics collected for this run.")


def render_agent_conversation(agent_log_path: Path):
    """Render agent.log as a chat conversation."""
    text = _read_file(agent_log_path)
    if not text.strip():
        st.info("Agent log is empty.")
        return

    turns = _parse_agent_log(text)
    if not turns:
        st.code(text[:5000], language="text")
        return

    for turn in turns:
        role = turn["role"]
        content = turn["content"]
        if role == "USER":
            with st.expander(f"USER prompt ({len(content)} chars)", expanded=False):
                st.markdown(content[:10000])
        else:
            with st.expander(f"ASSISTANT response ({len(content)} chars)", expanded=True):
                st.markdown(content[:10000])


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="autollm Dashboard", layout="wide")
    st.title("autollm Dashboard")

    sweeps = load_sweeps()
    if not sweeps:
        st.warning("No sweeps found in results/. Run `make sweep SWEEP=name` to create one.")
        return

    # Sidebar: sweep selector
    with st.sidebar:
        st.header("Sweep")
        sweep_options = [s["display"] for s in sweeps]
        selected_idx = st.selectbox(
            "Select sweep",
            range(len(sweep_options)),
            format_func=lambda i: sweep_options[i],
            index=0,
        )
        sweep = sweeps[selected_idx]
        if sweep["goal"]:
            st.caption(f"Goal: {sweep['goal']}")
        if sweep["benchmark"]:
            st.caption(f"Benchmark: {sweep['benchmark']}")
        if sweep["created"]:
            st.caption(f"Created: {sweep['created'][:19]}")
        if sweep["latest_run"]:
            st.caption(f"Latest run: {sweep['latest_run']}")

        st.divider()
        if st.button("Refresh"):
            st.rerun()

    sweep_dir = sweep["path"]

    # Live run panel (auto-refreshing fragment)
    @st.fragment(run_every=3)
    def live_panel():
        progress = detect_live_run()
        if progress:
            run_dir_str = progress.get("run_dir", "")
            if run_dir_str and sweep_dir.name in run_dir_str:
                render_live_panel(progress, sweep_dir)
            elif run_dir_str:
                st.info(f"A run is in progress in a different sweep: `{run_dir_str}`")
                st.divider()

    live_panel()

    # Leaderboard
    runs = load_runs(sweep_dir)
    selected = render_leaderboard(runs, sweep["name"])

    # Run detail
    if "selected_run" in st.session_state:
        st.divider()
        render_run_detail(Path(st.session_state["selected_run"]))


if __name__ == "__main__":
    main()
