import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import ai_experiment  # noqa: E402


class AiExperimentHelpersTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
