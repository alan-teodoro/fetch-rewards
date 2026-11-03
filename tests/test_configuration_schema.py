import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rediscloud.config import load_and_validate, render
from rediscloud.config_common import ConfigError

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationSchemaTests(unittest.TestCase):
    def validate(self, config):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config))
            return load_and_validate(path)

    def test_all_versioned_examples_match_the_contract(self):
        paths = [
            *ROOT.glob("configs/*/subscriptions/*.json"),
            *ROOT.glob("tests/fixtures/configs/*.json"),
        ]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                load_and_validate(path)

    def test_invalid_nested_types_and_unknown_fields_are_rejected_without_echoing_values(
        self,
    ):
        baseline = json.loads(
            (ROOT / "tests/fixtures/configs/two-agents.json").read_text()
        )
        for key, value in (
            ("short_term_ttl_seconds", 1.5),
            ("long_term_ttl_seconds", True),
            ("extraction_cadence_seconds", "FAKE-SECRET"),
            ("summarization", {"enabled": "FAKE-SECRET"}),
            ("timeouts", {"typo": "FAKE-SECRET"}),
        ):
            with self.subTest(key=key):
                config = deepcopy(baseline)
                config["agent_memory_stores"]["shopping_agent"][key] = value
                with self.assertRaises(ConfigError) as error:
                    self.validate(config)
                self.assertIn(key, str(error.exception))
                self.assertNotIn("FAKE-SECRET", str(error.exception))

    def test_schema_annotation_and_long_descriptions_preserve_config_version(self):
        config = json.loads(
            (ROOT / "tests/fixtures/configs/two-agents.json").read_text()
        )
        config["$schema"] = "../../../schemas/rediscloud-config.schema.json"
        store = config["agent_memory_stores"]["shopping_agent"]
        store["custom_memory_types"][0]["description"] = "x" * 500
        store["custom_memory_types"][0]["fields"][0]["description"] = "x" * 500
        result = self.validate(config)
        self.assertEqual(result["schema_version"], 1)

    def test_non_json_numbers_and_boolean_schema_version_are_rejected(self):
        config = json.loads(
            (ROOT / "tests/fixtures/configs/two-agents.json").read_text()
        )
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                config["schema_version"] = value
                with self.assertRaises(ConfigError):
                    self.validate(config)

    def test_ambiguous_or_unsafe_agent_database_bindings_are_rejected(self):
        baseline = json.loads(
            (ROOT / "tests/fixtures/configs/two-agents.json").read_text()
        )
        cases = []
        ambiguous = deepcopy(baseline)
        ambiguous["agent_memory_stores"]["shopping_agent"]["database_id"] = 123
        cases.append(ambiguous)
        managed_id = deepcopy(baseline)
        next(iter(managed_id["databases"].values()))["database_id"] = 123
        cases.append(managed_id)
        plaintext = deepcopy(baseline)
        next(iter(plaintext["databases"].values()))["enable_tls"] = False
        cases.append(plaintext)
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ConfigError):
                self.validate(config)

    def test_external_database_id_takes_precedence_and_null_models_need_no_secret(self):
        config = json.loads(
            (ROOT / "tests/fixtures/configs/two-agents.json").read_text()
        )
        database = next(iter(config["databases"].values()))
        database.update(mode="external", database_id=123, name="descriptive-name")
        store = config["agent_memory_stores"]["shopping_agent"]
        store.update(llm=None, embedding=None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config))
            manifest = render(path, Path(folder) / "render")
            item = next(
                x
                for x in manifest["agent_memory_stores"]
                if x["key"] == "shopping_agent"
            )
            values = json.loads(Path(item["tfvars_path"]).read_text())
            self.assertEqual(values["database_id"], 123)
            self.assertNotIn("database_name", values)
            self.assertNotIn("llm_api_key", values)
