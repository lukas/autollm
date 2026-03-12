#!/usr/bin/env python3
"""Generate kubeconfig from template using KUBECONFIG_SERVER and KUBECONFIG_TOKEN from .env."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV = PROJECT_ROOT / ".env"
TEMPLATE = PROJECT_ROOT / "kubeconfig.template"
OUT = PROJECT_ROOT / "kubeconfig"


def load_env() -> dict[str, str]:
    out = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    env = load_env()
    server = env.get("KUBECONFIG_SERVER", "").strip()
    token = env.get("KUBECONFIG_TOKEN", "").strip()
    if not server or not token:
        print("Need KUBECONFIG_SERVER and KUBECONFIG_TOKEN in .env")
        print("Copy .env.example to .env and fill in values.")
        print("Or copy your kubeconfig to autollm/kubeconfig directly.")
        return 1
    if not TEMPLATE.exists():
        print(f"Template not found: {TEMPLATE}")
        return 1
    text = TEMPLATE.read_text()
    text = text.replace("__KUBECONFIG_SERVER__", server)
    text = text.replace("__KUBECONFIG_TOKEN__", token)
    OUT.write_text(text)
    print(f"Generated {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
