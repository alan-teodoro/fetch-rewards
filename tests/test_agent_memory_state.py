import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rediscloud.agent_memory_state import agent_destroy_variables


class AgentMemoryStateTests(unittest.TestCase):
    def test_current_state_blocks_round_trip_to_stack_inputs_without_secrets(self):
        values = {
            "extraction_strategy": "pipeline",
            "custom_memory_types": [
                {
                    "name": "preference",
                    "description": "Preference",
                    "fields": [
                        {"name": "topic", "description": "Topic", "type": "str"}
                    ],
                    "extraction_strategy": [
                        {"enabled": True, "prompt": "Keep stable facts"}
                    ],
                }
            ],
            "summarization": [
                {"enabled": True, "event_count": [{"threshold": 20, "retain_count": 5}]}
            ],
            "long_term_memory_exclusions": [
                {
                    "enabled": True,
                    "semantic": [],
                    "built_in_detectors": [
                        {
                            "enabled": True,
                            "detectors": [{"id": "email", "enabled": True}],
                        }
                    ],
                    "custom_detectors": [
                        {
                            "enabled": True,
                            "detectors": [
                                {
                                    "name": "account",
                                    "enabled": True,
                                    "matcher": [
                                        {
                                            "kind": "regex",
                                            "regex": [{"pattern": "ACC-[0-9]+"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "timeouts": [{"delete": "40m"}],
            "llm": [
                {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "credentials": [{"api_key": "FAKE-OLD-SECRET"}],
                }
            ],
            "embedding": [
                {
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "credentials": [],
                }
            ],
        }
        original = deepcopy(values)
        result = agent_destroy_variables(values, "old-agent", 123)
        self.assertEqual(values, original)
        self.assertEqual(result["extraction_strategy"], "pipeline")
        self.assertEqual(result["summarization"]["event_count"]["threshold"], 20)
        self.assertEqual(
            result["custom_memory_types"][0]["extraction_strategy"]["prompt"],
            "Keep stable facts",
        )
        exclusions = result["long_term_memory_exclusions"]
        self.assertIsNone(exclusions["semantic"])
        self.assertEqual(
            exclusions["custom_detectors"]["detectors"][0]["matcher"]["regex"][
                "pattern"
            ],
            "ACC-[0-9]+",
        )
        self.assertEqual(result["llm"]["model"], "gpt-4o-mini")
        self.assertEqual(result["timeouts"]["delete"], "40m")
        self.assertNotIn("FAKE-OLD-SECRET", str(result))

    def test_legacy_objects_are_supported_without_mutating_state(self):
        values = {
            "summarization": {
                "enabled": True,
                "event_count": {"threshold": 10, "retain_count": 2},
            },
            "custom_memory_types": [
                {
                    "name": "preference",
                    "description": "Preference",
                    "fields": [],
                    "extraction_strategy": {"enabled": False, "prompt": "Skip"},
                }
            ],
        }
        original = deepcopy(values)
        result = agent_destroy_variables(values, "legacy-agent", 123)
        self.assertEqual(values, original)
        self.assertEqual(result["summarization"], values["summarization"])
        self.assertEqual(result["custom_memory_types"], values["custom_memory_types"])

    def test_ambiguous_or_malformed_blocks_stop_reconciliation(self):
        for value in ([{}, {}], [None], "bad", 1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "reconcile manually"),
            ):
                agent_destroy_variables({"summarization": value}, "bad-agent", 123)

    def test_partial_models_stop_reconciliation_and_empty_blocks_are_absent(self):
        with self.assertRaisesRegex(ValueError, "incomplete customer-managed"):
            agent_destroy_variables(
                {"llm": [{"provider": "openai", "model": "model"}], "embedding": []},
                "agent",
                123,
            )
        result = agent_destroy_variables({"llm": [], "embedding": []}, "agent", 123)
        self.assertNotIn("llm_api_key", result)
