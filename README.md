# autollm

Benchmark harness, AI optimizer agent, and dashboard for vLLM.

**Requires:** [runllm](runllm/) as a git submodule for vLLM config. Clone with `--recurse-submodules` or run `git submodule update --init` after clone.

## Quick start

```bash
# Clone (includes runllm submodule)
git clone --recurse-submodules https://github.com/lukas/autollm
cd autollm

# 1. Start vLLM (from runllm submodule)
cd runllm && make apply && make forward

# 2. In another terminal (from autollm root): start dashboard
make dashboard

# 3. Open http://localhost:8765/ and click Start
```

## Make targets

| Target | Description |
|--------|-------------|
| `make dashboard` | Start the web dashboard (Start/Stop, benchmark runs) |
| `make benchmark-run` | Run benchmark, save to results/runs/ |
| `make ai-optimize` | Run AI optimizer (Claude/OpenAI suggests vLLM config changes) |

## Environment

- `VLLM_CONFIG` – Path to vLLM YAML (default: `runllm/vllm-qwen.yaml`)
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` – For AI optimizer
- `AI_PROVIDER` – `anthropic` (default) or `openai`
