#!/usr/bin/env python3
"""One-shot script to serialize an SGLang model to tensorizer format.

Intended to run as a K8s Job on the same GPU nodes where the model will
be served. Loads the model via SGLang's normal pipeline, then writes
per-TP-rank .tensors files to the shared PVC.

Usage (local, single GPU):
    python scripts/tensorize_sglang.py \
        --model-path Qwen/Qwen2.5-1.5B-Instruct \
        --output-dir /mnt/models/sglang/Qwen/Qwen2.5-1.5B-Instruct/v1 \
        --tp-size 1

Usage (Kimi, 8×H200):
    python scripts/tensorize_sglang.py \
        --model-path moonshotai/Kimi-K2.5 \
        --output-dir /mnt/models/sglang/moonshotai/Kimi-K2.5/v1 \
        --tp-size 8 \
        --trust-remote-code \
        --max-model-len 8192

The output directory will contain:
    model-rank-000.tensors  (for TP rank 0)
    model-rank-001.tensors  (for TP rank 1)
    ...
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("tensorize_sglang")


def parse_args():
    p = argparse.ArgumentParser(description="Serialize SGLang model to tensorizer format")
    p.add_argument("--model-path", required=True, help="HuggingFace model ID or local path")
    p.add_argument("--output-dir", required=True, help="Directory for .tensors output files")
    p.add_argument("--tp-size", type=int, default=1, help="Tensor parallel size")
    p.add_argument("--trust-remote-code", action="store_true")
    p.add_argument("--max-model-len", type=int, default=None)
    p.add_argument("--dtype", default="auto", choices=["auto", "float16", "bfloat16"])
    p.add_argument("--download-dir", default=None, help="HF download cache directory")
    p.add_argument("--mem-fraction-static", type=float, default=0.9)
    return p.parse_args()


def tensorize_rank(rank: int, args):
    """Load the model for a given TP rank and serialize it."""
    import torch

    torch.cuda.set_device(rank)

    from sglang.srt.configs.device_config import DeviceConfig
    from sglang.srt.configs.load_config import LoadConfig, LoadFormat
    from sglang.srt.configs.model_config import ModelConfig
    from sglang.srt.model_loader import get_model
    from sglang.srt.model_loader.loader import TensorizerModelLoader

    load_config = LoadConfig(
        load_format=LoadFormat.AUTO,
        download_dir=args.download_dir,
    )
    device_config = DeviceConfig(device=f"cuda:{rank}")

    logger.info("Rank %d: loading model %s via SGLang default loader...", rank, args.model_path)
    t0 = time.perf_counter()
    model = get_model(
        model_config=ModelConfig.from_cli(
            model_path=args.model_path,
            trust_remote_code=args.trust_remote_code,
            dtype=args.dtype,
            context_length=args.max_model_len,
        ),
        load_config=load_config,
        device_config=device_config,
    )
    load_elapsed = time.perf_counter() - t0
    logger.info("Rank %d: model loaded in %.1fs", rank, load_elapsed)

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, f"model-rank-{rank:03d}.tensors")

    logger.info("Rank %d: serializing to %s ...", rank, output_path)
    t0 = time.perf_counter()
    TensorizerModelLoader.save_model(model, output_path)
    ser_elapsed = time.perf_counter() - t0

    file_size_gb = os.path.getsize(output_path) / (1024**3)
    logger.info(
        "Rank %d: serialized %.2f GB in %.1fs (%.1f GB/s)",
        rank, file_size_gb, ser_elapsed, file_size_gb / ser_elapsed,
    )

    del model
    torch.cuda.empty_cache()


def main():
    args = parse_args()

    if args.tp_size == 1:
        tensorize_rank(0, args)
    else:
        logger.info(
            "TP=%d serialization requires running with torchrun or "
            "inside an SGLang TP-aware launcher. For now, this script "
            "handles TP=1 directly. For TP>1, use the K8s Job template.",
            args.tp_size,
        )
        logger.info(
            "Alternative: load the model on a single GPU per rank "
            "sequentially (slow but works without distributed setup)."
        )
        for rank in range(args.tp_size):
            logger.warning(
                "Rank %d: sequential single-GPU serialization is a "
                "placeholder. For production TP>1 serialization, use "
                "the distributed launcher.",
                rank,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
