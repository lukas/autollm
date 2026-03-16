import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import ai_experiment  # noqa: E402


class AiExperimentHelpersTest(unittest.TestCase):
    def test_run_retro_helpers_prefer_new_name_and_fallback_to_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)

            legacy_path = run_dir / "RETRO.md"
            legacy_path.write_text("# Legacy retro\n\nold details\n")
            self.assertEqual(ai_experiment._read_run_retro_text(run_dir), "# Legacy retro\n\nold details")

            new_path = run_dir / "RUN_RETRO.md"
            new_path.write_text("# Run retro\n\nnew details\n")
            self.assertEqual(ai_experiment._read_run_retro_text(run_dir), "# Run retro\n\nnew details")

    def test_stable_base_pod_name_strips_repeated_suffixes(self) -> None:
        self.assertEqual(ai_experiment._stable_base_pod_name("sglang-kimi-15173225"), "sglang-kimi")
        self.assertEqual(
            ai_experiment._stable_base_pod_name("sglang-kimi-15173225-15173225"),
            "sglang-kimi",
        )
        self.assertEqual(ai_experiment._stable_base_pod_name("vllm-kimi"), "vllm-kimi")

    def test_sample_message_accepts_reasoning_content(self) -> None:
        self.assertTrue(
            ai_experiment._sample_message_has_output(
                {"content": None, "reasoning_content": "hello from kimi"}
            )
        )
        self.assertTrue(
            ai_experiment._sample_message_has_output(
                {"content": "", "tool_calls": [{"id": "call_1"}]}
            )
        )
        self.assertFalse(ai_experiment._sample_message_has_output({"content": None}))

    def test_summarize_pod_state_flags_unschedulable(self) -> None:
        summary, fatal = ai_experiment._summarize_pod_state(
            {
                "status": {
                    "phase": "Pending",
                    "conditions": [
                        {
                            "type": "PodScheduled",
                            "status": "False",
                            "reason": "Unschedulable",
                            "message": "0/4 nodes are available",
                        }
                    ],
                }
            }
        )
        self.assertIn("phase=Pending", summary)
        self.assertIn("PodScheduled=False:Unschedulable", summary)
        self.assertIn("unschedulable", fatal.lower())

    def test_summarize_pod_state_flags_container_wait_errors(self) -> None:
        summary, fatal = ai_experiment._summarize_pod_state(
            {
                "status": {
                    "phase": "Pending",
                    "containerStatuses": [
                        {
                            "name": "vllm",
                            "state": {
                                "waiting": {
                                    "reason": "ImagePullBackOff",
                                    "message": "Back-off pulling image",
                                }
                            },
                        }
                    ],
                }
            }
        )
        self.assertIn("vllm=waiting:ImagePullBackOff", summary)
        self.assertIn("ImagePullBackOff", fatal)

    def test_infrastructure_error_treats_unschedulable_gpu_as_cluster_issue(self) -> None:
        result = (
            "Pod startup error (pod_wait): Pod unschedulable: 0/4 nodes are available: "
            "4 Insufficient nvidia.com/gpu. no new claims to deallocate"
        )
        self.assertTrue(ai_experiment._is_infrastructure_error(result))
        guidance = ai_experiment._infrastructure_error_guidance(result)
        self.assertTrue(any("cluster-capacity issue" in line for line in guidance))
        self.assertTrue(any("Retry later or free capacity" in line for line in guidance))

    def test_research_memory_uses_cache_when_log_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sweep_dir = Path(tmpdir)
            log_path, memory_path, meta_path = ai_experiment._research_cache_paths(sweep_dir)
            log_path.write_text(
                "# Sweep research log\n\n"
                "## 2026-03-16T00:00:00 | search_web\n"
                "- Run: `20260316_000000`\n"
                "- Input: `vllm prefix caching`\n"
            )

            first = ai_experiment._get_or_refresh_research_memory(sweep_dir, lambda prompt: "cached research memory")
            self.assertEqual(first, "cached research memory")
            self.assertTrue(memory_path.exists())
            self.assertTrue(meta_path.exists())

            second = ai_experiment._get_or_refresh_research_memory(
                sweep_dir,
                lambda prompt: (_ for _ in ()).throw(AssertionError("should have used cached research memory")),
            )
            self.assertEqual(second, "cached research memory")

    def test_full_retro_writes_md_and_txt_and_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sweep_dir = Path(tmpdir)
            run_dir = sweep_dir / "20260316_000000"
            run_dir.mkdir()
            (run_dir / "RUN_RETRO.md").write_text("# Run retro\n\n- one useful lesson\n")

            first = ai_experiment._get_or_refresh_full_retro(
                sweep_dir,
                lambda prompt: "# Full sweep retro\n\n## Confirmed wins\n- useful synthesis",
            )
            self.assertIn("Full sweep retro", first)
            self.assertEqual((sweep_dir / "FULL_RETRO.md").read_text().strip(), first)
            self.assertEqual((sweep_dir / "FULL_RETRO.txt").read_text().strip(), first)

            second = ai_experiment._get_or_refresh_full_retro(
                sweep_dir,
                lambda prompt: (_ for _ in ()).throw(AssertionError("should have used cached full retro")),
            )
            self.assertEqual(second, first)

    def test_full_retro_refreshes_when_same_run_retro_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sweep_dir = Path(tmpdir)
            run_dir = sweep_dir / "20260316_000000"
            run_dir.mkdir()
            retro_path = run_dir / "RUN_RETRO.md"
            retro_path.write_text("# Run retro\n\n- first version\n")

            first = ai_experiment._get_or_refresh_full_retro(sweep_dir, lambda prompt: "first synthesis")
            self.assertEqual(first, "first synthesis")

            retro_path.write_text("# Run retro\n\n- first version\n- second version\n")
            second = ai_experiment._get_or_refresh_full_retro(sweep_dir, lambda prompt: "second synthesis")
            self.assertEqual(second, "second synthesis")
            self.assertEqual((sweep_dir / "FULL_RETRO.md").read_text().strip(), "second synthesis")


if __name__ == "__main__":
    unittest.main()
