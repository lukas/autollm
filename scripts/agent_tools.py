#!/usr/bin/env python3
"""
Agent tool-calling framework for the vLLM optimizer.

Defines tools, executes them, and runs an agentic loop that works
with both Anthropic Messages API and OpenAI Responses API.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# ── Tool schema definitions ──────────────────────────────────────────────────
# Common format: converted to provider-specific shapes at call time.

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "search_web",
        "description": (
            "Search the web using Exa deep search. Returns titles, URLs, and highlighted "
            "snippets. Great for vLLM docs, GPU tuning guides, CUDA optimization, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch a web page and return its text content (truncated to 20k chars). Uses Exa for clean extraction.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file from the project directory. Path is relative to project root. "
            "Allowed prefixes: results/, runllm/, docs/, scripts/. "
            "Returns content truncated to 50k chars."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path, e.g. 'results/sweep-qwen-throughput/baseline/benchmarks.json'",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write a file to the run-specific experiment directory (results/sweep-NAME/TIMESTAMP/runllm/). "
            "Only 'vllm-config.yaml' and 'Makefile' are allowed. This NEVER writes to the project root "
            "or the shared runllm/ — only to the isolated per-run copy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Filename to write: 'vllm-config.yaml' or 'Makefile'",
                },
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories at the given path (relative to project root).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path, e.g. 'results/sweep-qwen-throughput/'",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional glob pattern to filter, e.g. '*.json'",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Run a shell command (30s timeout). Prefer the dedicated kubectl tools "
            "for Kubernetes operations. Use for quick inspections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "run_benchmark",
        "description": (
            "Deploy the current experiment config and run the benchmark suite. "
            "You MUST call write_file('vllm-config.yaml', ...) first. "
            "Long-running (~2 min). Returns benchmark metrics or error details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Short description of the config change being tested",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "read_logs",
        "description": "Read logs from a previous benchmark run directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_name": {
                    "type": "string",
                    "description": "Run directory name, e.g. '20260312_194524' or 'baseline'",
                },
                "log_type": {
                    "type": "string",
                    "enum": ["deploy", "kubectl", "harness", "benchmark", "agent", "metadata"],
                    "description": (
                        "deploy=deploy.log, kubectl=kubectl_logs.txt, "
                        "harness=harness_output.txt, benchmark=benchmarks.json, "
                        "agent=agent.log, metadata=run_metadata.json"
                    ),
                },
            },
            "required": ["run_name", "log_type"],
        },
    },
    {
        "name": "kubectl_get",
        "description": "Run 'kubectl get <resource>' and return the output.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "Resource type or name, e.g. 'pods', 'nodes', 'pod/vllm'",
                },
                "output": {
                    "type": "string",
                    "enum": ["wide", "yaml", "json", "name"],
                    "description": "Output format (default: wide)",
                },
            },
            "required": ["resource"],
        },
    },
    {
        "name": "kubectl_logs",
        "description": "Get recent logs from a Kubernetes pod.",
        "parameters": {
            "type": "object",
            "properties": {
                "pod_name": {"type": "string", "description": "Pod name from vllm-config.yaml metadata.name"},
                "tail": {"type": "integer", "description": "Lines from end (default 200)"},
                "container": {"type": "string", "description": "Container name (optional)"},
            },
            "required": ["pod_name"],
        },
    },
]


# ── Context & Result ─────────────────────────────────────────────────────────

@dataclass
class ToolContext:
    """State and permissions for tool execution."""
    project_root: Path
    experiment_dir: Path
    run_dir: Path
    sweep_dir: Path | None
    sweep: str | None
    benchmark: str
    ts: str
    env: dict[str, str] = field(default_factory=dict)

    deploy_and_benchmark: Callable[..., tuple[bool, str]] | None = None

    config_written: bool = False
    config_content: str = ""
    benchmark_ran: bool = False
    benchmark_success: bool = False
    benchmark_result: str = ""
    # Keep one benchmark per agent loop so a single run directory maps to one config attempt.
    max_benchmarks: int = 1
    _benchmark_count: int = 0
    max_web_tool_calls: int = int(os.environ.get("AGENT_MAX_WEB_TOOL_CALLS", "20"))
    _web_tool_calls: int = 0

    tool_log: list[dict[str, Any]] = field(default_factory=list)
    log_path: Path | None = None


def _flush_log_entry(ctx: ToolContext, entry: dict[str, Any]) -> None:
    """Append a single conversation entry to the live agent log file."""
    if not ctx.log_path:
        return
    role = entry.get("role", "?")
    lines = [f"\n{'='*60}\n{role.upper()}\n{'='*60}\n"]

    if role == "assistant":
        text = entry.get("content", "")
        if isinstance(text, list):
            for block in text:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        lines.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        lines.append(f"\n--- tool_use: {block.get('name')} ---")
                        lines.append(json.dumps(block.get("input", {}), indent=2, default=str))
        elif isinstance(text, str):
            lines.append(text)
        tool_calls = entry.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            for tc in tool_calls:
                lines.append(f"\n--- tool_call: {tc.get('name', '?')} ---")
                lines.append(str(tc.get("arguments", "")))
    elif role in ("tool_results", "tool_result"):
        tool_name = entry.get("tool", "")
        if tool_name:
            lines.append(f"[{tool_name}]")
        tool_content = entry.get("tool_content", entry.get("content", ""))
        if isinstance(tool_content, list):
            for item in tool_content:
                if isinstance(item, dict):
                    tid = item.get("tool_use_id", "")
                    tc = item.get("tool_content", "")
                    if tid:
                        lines.append(f"\n--- result ({tid}) ---")
                    lines.append(str(tc))
                else:
                    lines.append(str(item))
        else:
            lines.append(json.dumps(tool_content, indent=2, default=str) if not isinstance(tool_content, str) else tool_content)
    else:
        lines.append(str(entry.get("content", "")))

    try:
        with open(ctx.log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")
    except Exception:
        pass


@dataclass
class AgentResult:
    """Outcome of a single agent loop run."""
    text: str = ""
    description: str = ""
    config_written: bool = False
    config_content: str = ""
    benchmark_ran: bool = False
    benchmark_success: bool = False
    benchmark_result: str = ""
    conversation: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int = 50_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n... (truncated)"


def _research_log_path(ctx: ToolContext) -> Path | None:
    if not ctx.sweep_dir:
        return None
    return ctx.sweep_dir / "RESEARCH_LOG.md"


def _append_research_log(ctx: ToolContext, tool_name: str, arguments: dict[str, Any], result: str) -> None:
    """Persist sweep-local web research so later runs can reuse it."""
    log_path = _research_log_path(ctx)
    if not log_path:
        return
    try:
        parts = []
        if not log_path.exists():
            parts.extend([
                "# Sweep research log",
                "",
                "This file captures external research done during this sweep.",
                "Use `RESEARCH_MEMORY.md` for the compact synthesized takeaways.",
                "",
            ])
        query_or_url = arguments.get("query") or arguments.get("url") or ""
        parts.extend([
            f"## {datetime.now().isoformat()} | {tool_name}",
            f"- Run: `{ctx.run_dir.name}`",
            f"- Input: `{str(query_or_url)[:500]}`",
            "",
            "```text",
            _truncate(result, 4000),
            "```",
            "",
        ])
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(parts))
    except Exception:
        pass


def _html_to_text(raw: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


ALLOWED_READ_PREFIXES = ("results/", "runllm/", "docs/", "scripts/")
ALLOWED_WRITE_FILES = {"vllm-config.yaml", "Makefile"}
SHELL_BLOCKLIST = re.compile(
    r"\b(rm\s+-rf|rm\s+-r|mkfs|dd\s+if|reboot|shutdown|kill\s+-9|pkill|chmod\s+777)\b", re.I
)

LOG_TYPE_MAP = {
    "deploy": "deploy.log",
    "kubectl": "kubectl_logs.txt",
    "harness": "harness_output.txt",
    "benchmark": "benchmarks.json",
    "agent": "agent.log",
    "metadata": "run_metadata.json",
}


# ── Tool Implementations ────────────────────────────────────────────────────

def _get_exa_key() -> str:
    """Get Exa API key from environment or .env files."""
    key = os.environ.get("EXA_API_KEY", "")
    if key:
        return key
    for env_file in (".env", "../.env"):
        p = Path(env_file)
        if not p.exists():
            p = Path(__file__).resolve().parent.parent / env_file.lstrip("../")
        if p.exists():
            try:
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("EXA_API_KEY=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip().strip("'\"")
            except Exception:
                pass
    return ""


def _exa_api_call(endpoint: str, payload: dict, timeout: int = 20) -> dict:
    """Make an authenticated Exa API call. Raises on failure."""
    api_key = _get_exa_key()
    if not api_key:
        raise RuntimeError("EXA_API_KEY not set")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.exa.ai/{endpoint}",
        data=data,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "vllm-optimizer/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tool_search_web(query: str) -> str:
    try:
        data = _exa_api_call("search", {
            "query": query,
            "type": "auto",
            "num_results": 8,
            "contents": {
                "highlights": {"max_characters": 4000},
            },
        })
        results: list[str] = []
        for r in data.get("results", []):
            title = r.get("title", "").strip()
            url = r.get("url", "")
            highlights = r.get("highlights", [])
            snippet = " ".join(h.strip() for h in highlights[:2]) if highlights else ""
            if title:
                entry = f"• {title}\n  {url}"
                if snippet:
                    entry += f"\n  {snippet[:400]}"
                results.append(entry)
        return "\n\n".join(results) if results else "No results found."
    except RuntimeError:
        return _fallback_search_web(query)
    except Exception as e:
        return f"Exa search error: {e}"


def _fallback_search_web(query: str) -> str:
    """DuckDuckGo HTML fallback when EXA_API_KEY is not set."""
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        results: list[str] = []
        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(.*?)</(?:a|span)',
            raw, re.DOTALL,
        ):
            href = m.group(1).strip()
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if title:
                results.append(f"• {title}\n  {href}\n  {snippet}")
            if len(results) >= 8:
                break
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {e}"


def _tool_fetch_url(url: str) -> str:
    # Try Exa /contents first for clean extraction
    try:
        data = _exa_api_call("contents", {
            "urls": [url],
            "text": {"max_characters": 20000},
        })
        results = data.get("results", [])
        if results and results[0].get("text"):
            title = results[0].get("title", "")
            text = results[0]["text"]
            header = f"# {title}\n\n" if title else ""
            return _truncate(header + text, 20_000)
    except Exception:
        pass
    # Fallback to direct fetch
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; vllm-optimizer/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        text = _html_to_text(raw)
        return _truncate(text, 20_000)
    except Exception as e:
        return f"Fetch error: {e}"


def _tool_read_file(path: str, ctx: ToolContext) -> str:
    path = path.lstrip("/")
    if not any(path.startswith(p) for p in ALLOWED_READ_PREFIXES):
        return f"Denied: path must start with one of {ALLOWED_READ_PREFIXES}"
    fp = (ctx.project_root / path).resolve()
    if not str(fp).startswith(str(ctx.project_root.resolve())):
        return "Denied: path escapes project root."
    if not fp.exists():
        return f"File not found: {path}"
    if fp.is_dir():
        children = sorted(fp.iterdir())[:100]
        listing = "\n".join(f.name + ("/" if f.is_dir() else "") for f in children)
        return f"(directory)\n{listing}"
    try:
        content = fp.read_text(errors="replace")
        return _truncate(content)
    except Exception as e:
        return f"Read error: {e}"


def _tool_write_file(path: str, content: str, ctx: ToolContext) -> str:
    basename = Path(path).name
    if basename not in ALLOWED_WRITE_FILES:
        return f"Denied: can only write {ALLOWED_WRITE_FILES}, got '{basename}'"
    if not ctx.experiment_dir.exists():
        return f"Error: experiment directory does not exist: {ctx.experiment_dir}"
    # Verify the experiment_dir is inside a sweep/run directory, not the shared runllm
    exp_resolved = ctx.experiment_dir.resolve()
    project_resolved = ctx.project_root.resolve()
    rel = str(exp_resolved.relative_to(project_resolved))
    if not rel.startswith("results/"):
        return f"Denied: experiment dir must be under results/, got {rel}"
    target = ctx.experiment_dir / basename
    try:
        target.write_text(content)
        if basename == "vllm-config.yaml":
            ctx.config_written = True
            ctx.config_content = content
            import shutil
            shutil.copy(target, ctx.run_dir / "vllm_config.yaml")
        return f"Wrote {basename} ({len(content)} bytes) to {rel}/{basename}"
    except Exception as e:
        return f"Write error: {e}"


def _tool_list_files(path: str, ctx: ToolContext, pattern: str | None = None) -> str:
    path = path.lstrip("/")
    fp = (ctx.project_root / path).resolve()
    if not str(fp).startswith(str(ctx.project_root.resolve())):
        return "Denied: path escapes project root."
    if not fp.exists():
        return f"Not found: {path}"
    if not fp.is_dir():
        return f"Not a directory: {path}"
    try:
        if pattern:
            children = sorted(fp.glob(pattern))[:200]
        else:
            children = sorted(fp.iterdir())[:200]
        lines = []
        for f in children:
            suffix = "/" if f.is_dir() else ""
            try:
                size = f.stat().st_size if f.is_file() else 0
                lines.append(f"{f.name}{suffix}  ({size:,} bytes)" if size else f"{f.name}{suffix}")
            except OSError:
                lines.append(f"{f.name}{suffix}")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"List error: {e}"


def _tool_run_shell(command: str, ctx: ToolContext) -> str:
    if SHELL_BLOCKLIST.search(command):
        return "Denied: command matches blocklist (destructive operations not allowed)."
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(ctx.project_root), env=ctx.env,
        )
        out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
        return _truncate(f"exit_code={r.returncode}\n{out}", 20_000)
    except subprocess.TimeoutExpired:
        return "Command timed out after 30s."
    except Exception as e:
        return f"Shell error: {e}"


def _tool_run_benchmark(description: str, ctx: ToolContext) -> str:
    if not ctx.config_written:
        return "Error: write vllm-config.yaml first (call write_file)."
    if ctx._benchmark_count >= ctx.max_benchmarks:
        return f"Error: max {ctx.max_benchmarks} benchmarks per agent loop reached."
    if ctx.deploy_and_benchmark is None:
        return "Error: benchmark runner not configured."
    ctx._benchmark_count += 1
    print(f"\n  [tool] run_benchmark: {description}")
    print(f"  [tool] Deploying and running benchmark ({ctx.benchmark})...\n")
    try:
        success, result = ctx.deploy_and_benchmark(
            ctx.experiment_dir, ctx.benchmark, ctx.run_dir, ctx.ts, sweep=ctx.sweep,
        )
        ctx.benchmark_ran = True
        ctx.benchmark_success = success
        ctx.benchmark_result = result
        if success:
            return f"Benchmark succeeded: {result}"
        else:
            deploy_log = ""
            kubectl_logs = ""
            if (ctx.run_dir / "deploy.log").exists():
                deploy_log = (ctx.run_dir / "deploy.log").read_text(errors="replace")[-4000:]
            if (ctx.run_dir / "kubectl_logs.txt").exists():
                kubectl_logs = (ctx.run_dir / "kubectl_logs.txt").read_text(errors="replace")[-4000:]
            return (
                f"Benchmark FAILED: {result}\n\n"
                f"deploy.log (last 4k):\n{deploy_log}\n\n"
                f"kubectl_logs (last 4k):\n{kubectl_logs}"
            )
    except Exception as e:
        return f"Benchmark error: {e}"


def _tool_read_logs(run_name: str, log_type: str, ctx: ToolContext) -> str:
    filename = LOG_TYPE_MAP.get(log_type)
    if not filename:
        return f"Unknown log_type: {log_type}. Valid: {list(LOG_TYPE_MAP.keys())}"
    runs_base = ctx.sweep_dir if ctx.sweep_dir else ctx.project_root / "results" / "runs"
    run_path = runs_base / run_name
    if not run_path.exists():
        return f"Run directory not found: {run_name}"
    fp = run_path / filename
    if not fp.exists():
        available = [f.name for f in run_path.iterdir() if f.is_file()]
        return f"File {filename} not found in {run_name}/. Available: {available}"
    try:
        content = fp.read_text(errors="replace")
        return _truncate(content)
    except Exception as e:
        return f"Read error: {e}"


def _tool_kubectl_get(resource: str, ctx: ToolContext, output: str | None = None) -> str:
    cmd = ["kubectl", "get", resource]
    if output:
        cmd.extend(["-o", output])
    else:
        cmd.extend(["-o", "wide"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=ctx.env)
        out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
        return _truncate(f"exit_code={r.returncode}\n{out}", 20_000)
    except subprocess.TimeoutExpired:
        return "kubectl timed out after 15s."
    except Exception as e:
        return f"kubectl error: {e}"


def _tool_kubectl_logs(
    pod_name: str, ctx: ToolContext, tail: int = 200, container: str | None = None,
) -> str:
    cmd = ["kubectl", "logs", pod_name, f"--tail={tail}"]
    if container:
        cmd.extend(["-c", container])
    else:
        cmd.append("--all-containers=true")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=ctx.env)
        out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
        return _truncate(out, 20_000)
    except subprocess.TimeoutExpired:
        return "kubectl logs timed out after 15s."
    except Exception as e:
        return f"kubectl logs error: {e}"


def execute_tool(name: str, arguments: dict[str, Any], ctx: ToolContext) -> str:
    """Dispatch a tool call and return the string result."""
    start = time.time()
    try:
        if name == "search_web":
            if ctx._web_tool_calls >= ctx.max_web_tool_calls:
                result = (
                    "Denied: web-tool budget reached for this run. "
                    "Use sweep research memory plus local leaderboard/retros/logs unless this is a genuinely new issue."
                )
            else:
                ctx._web_tool_calls += 1
                result = _tool_search_web(arguments["query"])
        elif name == "fetch_url":
            if ctx._web_tool_calls >= ctx.max_web_tool_calls:
                result = (
                    "Denied: web-tool budget reached for this run. "
                    "Use sweep research memory plus local leaderboard/retros/logs unless this is a genuinely new issue."
                )
            else:
                ctx._web_tool_calls += 1
                result = _tool_fetch_url(arguments["url"])
        elif name == "read_file":
            result = _tool_read_file(arguments["path"], ctx)
        elif name == "write_file":
            result = _tool_write_file(arguments["path"], arguments["content"], ctx)
        elif name == "list_files":
            result = _tool_list_files(arguments["path"], ctx, arguments.get("pattern"))
        elif name == "run_shell":
            result = _tool_run_shell(arguments["command"], ctx)
        elif name == "run_benchmark":
            result = _tool_run_benchmark(arguments.get("description", ""), ctx)
        elif name == "read_logs":
            result = _tool_read_logs(arguments["run_name"], arguments["log_type"], ctx)
        elif name == "kubectl_get":
            result = _tool_kubectl_get(arguments["resource"], ctx, arguments.get("output"))
        elif name == "kubectl_logs":
            result = _tool_kubectl_logs(
                arguments["pod_name"], ctx,
                arguments.get("tail", 200), arguments.get("container"),
            )
        else:
            result = f"Unknown tool: {name}"
    except Exception as e:
        result = f"Tool execution error: {e}"

    if name in {"search_web", "fetch_url"} and not result.startswith("Denied:"):
        _append_research_log(ctx, name, arguments, result)

    elapsed = time.time() - start
    ctx.tool_log.append({
        "tool": name, "arguments": arguments,
        "result_length": len(result), "elapsed_s": round(elapsed, 2),
    })
    print(f"  [tool] {name}({_summarize_args(arguments)}) -> {len(result)} chars ({elapsed:.1f}s)")
    return result


def _summarize_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f"{k}={s!r}")
    return ", ".join(parts)


# ── Provider Adapters ────────────────────────────────────────────────────────

def _tools_for_anthropic() -> list[dict[str, Any]]:
    """Convert common tool defs to Anthropic Messages API format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in TOOL_DEFS
    ]


def _tools_for_openai() -> list[dict[str, Any]]:
    """Convert common tool defs to OpenAI Responses API format."""
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        }
        for t in TOOL_DEFS
    ]


# ── Anthropic Agent Loop ────────────────────────────────────────────────────

def _run_anthropic_loop(
    system: str, messages: list[dict], model: str, ctx: ToolContext, max_turns: int,
) -> AgentResult:
    from anthropic import Anthropic

    client = Anthropic()
    tools = _tools_for_anthropic()
    conversation: list[dict[str, Any]] = []

    for turn in range(max_turns):
        print(f"  [agent] Anthropic call (turn {turn + 1}/{max_turns})...")
        resp = client.messages.create(
            model=model, max_tokens=8192, system=system,
            messages=messages, tools=tools,
        )

        assistant_content = resp.content
        messages.append({"role": "assistant", "content": assistant_content})
        asst_entry = {"role": "assistant", "content": _serialize_anthropic_content(assistant_content)}
        conversation.append(asst_entry)
        _flush_log_entry(ctx, asst_entry)

        text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
        tool_uses = [b for b in assistant_content if hasattr(b, "name")]

        if resp.stop_reason != "tool_use" or not tool_uses:
            return AgentResult(
                text="\n".join(text_parts),
                config_written=ctx.config_written,
                config_content=ctx.config_content,
                benchmark_ran=ctx.benchmark_ran,
                benchmark_success=ctx.benchmark_success,
                benchmark_result=ctx.benchmark_result,
                conversation=conversation,
                tool_log=ctx.tool_log,
            )

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            result_str = execute_tool(tu.name, tu.input, ctx)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})
        tool_entry = {"role": "tool_results", "content": [
            {"tool_use_id": tr["tool_use_id"], "tool_content": tr["content"]} for tr in tool_results
        ]}
        conversation.append(tool_entry)
        _flush_log_entry(ctx, tool_entry)

    return AgentResult(error="Max tool-calling turns reached", conversation=conversation, tool_log=ctx.tool_log)


def _serialize_anthropic_content(content: list) -> list[dict]:
    """Serialize Anthropic content blocks for conversation logging."""
    out = []
    for block in content:
        if hasattr(block, "text"):
            out.append({"type": "text", "text": block.text})
        elif hasattr(block, "name"):
            out.append({"type": "tool_use", "name": block.name, "input": block.input or {}})
    return out


# ── OpenAI Agent Loop ───────────────────────────────────────────────────────

def _serialize_openai_response_output(output: list[Any]) -> list[dict[str, Any]]:
    """Serialize Responses API output items for conversation logging."""
    out: list[dict[str, Any]] = []
    for item in output or []:
        item_type = getattr(item, "type", "")
        if item_type == "function_call":
            raw_arguments = getattr(item, "arguments", "") or ""
            try:
                parsed_input = json.loads(raw_arguments) if raw_arguments else {}
            except json.JSONDecodeError:
                parsed_input = {"_raw": raw_arguments}
            out.append({"type": "tool_use", "name": getattr(item, "name", ""), "input": parsed_input})
            continue
        if item_type == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", "") == "output_text":
                    out.append({"type": "text", "text": getattr(content, "text", "")})
    return out


def _extract_openai_response_text(resp: Any) -> str:
    """Extract assistant text from a Responses API response."""
    output_text = getattr(resp, "output_text", "") or ""
    if output_text:
        return output_text
    parts: list[str] = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", "") == "output_text":
                text = getattr(content, "text", "") or ""
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _extract_openai_function_calls(resp: Any) -> list[Any]:
    """Extract function_call items from a Responses API response."""
    return [
        item for item in (getattr(resp, "output", []) or [])
        if getattr(item, "type", "") == "function_call"
    ]


def _run_openai_loop(
    system: str, messages: list[dict], model: str, ctx: ToolContext, max_turns: int,
) -> AgentResult:
    from openai import OpenAI

    client = OpenAI()
    tools = _tools_for_openai()
    conversation: list[dict[str, Any]] = []
    input_items: list[Any] = list(messages)

    for turn in range(max_turns):
        print(f"  [agent] OpenAI call (turn {turn + 1}/{max_turns})...")
        resp = client.responses.create(
            model=model,
            instructions=system,
            input=input_items,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=True,
            max_output_tokens=8192,
        )

        input_items.extend(getattr(resp, "output", []) or [])
        asst_entry = {
            "role": "assistant",
            "content": _serialize_openai_response_output(getattr(resp, "output", []) or []),
        }
        conversation.append(asst_entry)
        _flush_log_entry(ctx, asst_entry)

        tool_calls = _extract_openai_function_calls(resp)
        if not tool_calls:
            return AgentResult(
                text=_extract_openai_response_text(resp),
                config_written=ctx.config_written,
                config_content=ctx.config_content,
                benchmark_ran=ctx.benchmark_ran,
                benchmark_success=ctx.benchmark_success,
                benchmark_result=ctx.benchmark_result,
                conversation=conversation,
                tool_log=ctx.tool_log,
            )

        for tc in tool_calls:
            try:
                args = json.loads(getattr(tc, "arguments", "") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": getattr(tc, "arguments", "")}

            result_str = execute_tool(getattr(tc, "name", ""), args, ctx)
            input_items.append({
                "type": "function_call_output",
                "call_id": getattr(tc, "call_id", ""),
                "output": result_str,
            })
            tool_entry = {"role": "tool_result", "tool": getattr(tc, "name", ""), "tool_content": result_str}
            conversation.append(tool_entry)
            _flush_log_entry(ctx, tool_entry)

    return AgentResult(error="Max tool-calling turns reached", conversation=conversation, tool_log=ctx.tool_log)


# ── Public API ───────────────────────────────────────────────────────────────

def run_agent(
    system_prompt: str,
    user_prompt: str,
    provider: str,
    model: str,
    ctx: ToolContext,
    max_turns: int = 50,
) -> AgentResult:
    """
    Run the tool-calling agent loop.

    The agent receives the system prompt and user prompt, and can use tools
    to gather information, write configs, and optionally run benchmarks.
    Returns an AgentResult with the final state.
    """
    messages = [{"role": "user", "content": user_prompt}]

    if ctx.log_path:
        ctx.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ctx.log_path, "w", encoding="utf-8") as f:
            f.write("# Agent Tool-Calling Log\n")
        _flush_log_entry(ctx, {"role": "system", "content": system_prompt})
        _flush_log_entry(ctx, {"role": "user", "content": user_prompt})

    if provider == "anthropic":
        result = _run_anthropic_loop(system_prompt, messages, model, ctx, max_turns)
    elif provider == "openai":
        result = _run_openai_loop(system_prompt, messages, model, ctx, max_turns)
    else:
        return AgentResult(error=f"Unknown provider: {provider}")

    if not result.description and result.text:
        result.description = _extract_description_from_text(result.text)

    return result


def _extract_description_from_text(text: str) -> str:
    """Pull a short description from the agent's final text."""
    for pattern in [
        r"(?:description|strategy|summary|experiment):\s*(.+?)(?:\n\n|```|$)",
        r"(?:Changed knobs?|What changed):\s*(.+?)(?:\n\n|```|$)",
    ]:
        m = re.search(pattern, text, re.I | re.DOTALL)
        if m:
            return m.group(1).strip()[:500]
    return text[:300].strip()
