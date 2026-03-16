import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import start_sweep  # noqa: E402


class StartSweepHelpersTest(unittest.TestCase):
    def test_resolve_model_variants_defaults_to_family_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("kimi-vllm", "kimi-sglang"):
                variant_dir = root / name
                variant_dir.mkdir()
                (variant_dir / "vllm-config.yaml").write_text("apiVersion: v1\nkind: Pod\n")

            variants = start_sweep._resolve_model_variants(root, "kimi")
            self.assertEqual(variants, ["kimi-vllm", "kimi-sglang"])

    def test_resolve_model_variants_keeps_requested_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("kimi-vllm", "kimi-sglang"):
                variant_dir = root / name
                variant_dir.mkdir()
                (variant_dir / "vllm-config.yaml").write_text("apiVersion: v1\nkind: Pod\n")

            variants = start_sweep._resolve_model_variants(root, "kimi", "kimi-sglang,kimi-vllm")
            self.assertEqual(variants, ["kimi-sglang", "kimi-vllm"])

    def test_resolve_baseline_variant_prefers_explicit_variant_then_family_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("kimi-vllm", "kimi-sglang"):
                variant_dir = root / name
                variant_dir.mkdir()
                (variant_dir / "vllm-config.yaml").write_text("apiVersion: v1\nkind: Pod\n")

            variants = ["kimi-vllm", "kimi-sglang"]
            self.assertEqual(start_sweep._resolve_baseline_variant(root, "kimi", variants), "kimi-vllm")
            self.assertEqual(start_sweep._resolve_baseline_variant(root, "kimi-sglang", variants), "kimi-sglang")
            self.assertEqual(
                start_sweep._resolve_baseline_variant(root, "kimi", variants, baseline_variant="kimi-sglang"),
                "kimi-sglang",
            )

    def test_allow_backend_switches_when_multiple_backends_present(self) -> None:
        self.assertFalse(start_sweep._allow_backend_switches(["kimi-vllm"]))
        self.assertTrue(start_sweep._allow_backend_switches(["kimi-vllm", "kimi-sglang"]))


if __name__ == "__main__":
    unittest.main()
