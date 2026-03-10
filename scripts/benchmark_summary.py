#!/usr/bin/env python3
"""Generate HTML summary from Guideline benchmarks.json."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _paths(run_dir: Path | None = None) -> tuple[Path, Path, Path]:
    base = PROJECT_ROOT / "results"
    if run_dir:
        return run_dir, run_dir / "benchmarks.json", run_dir / "summary.html"
    return base, base / "benchmarks.json", base / "summary.html"


def main(run_dir: Path | None = None) -> None:
    _, benchmarks_json, summary_html = _paths(run_dir)
    if not benchmarks_json.exists():
        return

    with open(benchmarks_json) as f:
        data = json.load(f)

    benchmarks = data.get("benchmarks", [])
    if not benchmarks:
        return

    rows = []
    for b in benchmarks:
        m = b.get("metrics", {})
        cfg = b.get("config", {})
        strategy = cfg.get("strategy", {})
        if isinstance(strategy, dict):
            strategy = strategy.get("type_", "?")
        else:
            strategy = str(strategy) if strategy else "?"

        def _suc(obj, key):
            o = obj.get(key, {}) if isinstance(obj, dict) else {}
            return o.get("successful") if isinstance(o, dict) else o

        req_lat, ttft, itl, tok_sec, rps_obj = _suc(m, "request_latency"), _suc(m, "time_to_first_token_ms"), _suc(m, "inter_token_latency_ms"), _suc(m, "tokens_per_second"), _suc(m, "requests_per_second")

        def _mean(d):
            return d.get("mean") if isinstance(d, dict) else None
        def _p95(d):
            return (d.get("percentiles") or {}).get("p95") if isinstance(d, dict) else None

        req_mean, req_p95 = _mean(req_lat), _p95(req_lat)
        rows.append({
            "strategy": strategy,
            "requests_per_sec": _mean(rps_obj),
            "req_latency_mean_ms": (req_mean * 1000) if req_mean is not None else None,
            "req_latency_p95_ms": (req_p95 * 1000) if req_p95 is not None else None,
            "ttft_mean_ms": _mean(ttft),
            "ttft_p95_ms": _p95(ttft),
            "itl_mean_ms": _mean(itl),
            "itl_p95_ms": _p95(itl),
            "throughput_tok_s": (tok_sec.get("median") if isinstance(tok_sec, dict) else None) or _mean(tok_sec),
        })

    html = _render(rows, data.get("args", {}), run_dir=run_dir)
    summary_html.parent.mkdir(parents=True, exist_ok=True)
    summary_html.write_text(html, encoding="utf-8")


def _fmt(v, unit="") -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:.2f}{unit}"
    return str(v)


def _render(rows: list, args: dict, run_dir: Path | None = None) -> str:
    target = args.get("target", "?")
    profile = args.get("profile", "?")
    data_cfg = args.get("data", ["?"])
    data_str = data_cfg[0] if isinstance(data_cfg, list) else str(data_cfg)
    nav_runs = ' · <a href="../index.html">All runs</a>' if run_dir else ' · <a href="runs/index.html">All runs</a>'

    table_rows = ""
    for r in rows:
        table_rows += f"""
        <tr>
            <td>{r['strategy']}</td>
            <td>{_fmt(r['requests_per_sec'])}</td>
            <td>{_fmt(r['req_latency_mean_ms'], ' ms')}</td>
            <td>{_fmt(r['req_latency_p95_ms'], ' ms')}</td>
            <td>{_fmt(r['ttft_mean_ms'], ' ms')}</td>
            <td>{_fmt(r['ttft_p95_ms'], ' ms')}</td>
            <td>{_fmt(r['itl_mean_ms'], ' ms')}</td>
            <td>{_fmt(r['itl_p95_ms'], ' ms')}</td>
            <td>{_fmt(r['throughput_tok_s'], ' tok/s')}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Benchmark Summary</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
    th {{ background: #f5f5f5; }}
    .nav a {{ color: #2A8EFD; margin-right: 1rem; }}
  </style>
</head>
<body>
  <div class="nav"><a href="benchmarks.html">Full report</a>{nav_runs}</div>
  <h1>Benchmark Summary</h1>
  <div class="meta">Target: {target} · Profile: {profile} · Data: {data_str}</div>
  <table>
    <thead>
      <tr>
        <th>Strategy</th>
        <th>Req/s</th>
        <th>Latency (mean)</th>
        <th>Latency (p95)</th>
        <th>TTFT (mean)</th>
        <th>TTFT (p95)</th>
        <th>ITL (mean)</th>
        <th>ITL (p95)</th>
        <th>Throughput</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    import sys
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(run_dir=run_dir)
