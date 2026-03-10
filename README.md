# autollm

Benchmark harness, AI optimizer agent, and dashboard for vLLM.

**Requires:** [runllm](../runllm) (sibling) for vLLM config. Start vLLM with `cd runllm && make apply && make forward`.

## Quick start

```bash
# 1. Start vLLM (in runllm)
cd runllm && make apply && make forward

# 2. In another terminal: start dashboard
cd autollm && make dashboard

# 3. Open http://localhost:8765/ and click Start
```

## Make targets

| Target | Description |
|--------|-------------|
| `make dashboard` | Start the web dashboard (Start/Stop, benchmark runs) |
| `make benchmark-run` | Run benchmark, save to results/runs/ |
| `make ai-optimize` | Run AI optimizer (Claude/OpenAI suggests vLLM config changes) |

## Environment

- `VLLM_CONFIG` – Path to vLLM YAML (default: `../runllm/vllm-qwen.yaml`)
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` – For AI optimizer
- `AI_PROVIDER` – `anthropic` (default) or `openai`
