"""Exercise the stack/state contract with Terraform and the built provider, without cloud calls."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rediscloud.agent_memory_state import agent_destroy_variables


@unittest.skipUnless(
    os.environ.get("MOCK_PROVIDER_BINARY"),
    "Built provider required for the Terraform contract test",
)
class TerraformContractTests(unittest.TestCase):
    def test_current_provider_state_produces_a_deletion_only_plan(self):
        terraform = os.environ.get("TF_ACC_TERRAFORM_PATH") or shutil.which("terraform")
        self.assertTrue(terraform, "Install the pinned Terraform version")
        binary = Path(os.environ["MOCK_PROVIDER_BINARY"]).resolve()
        self.assertTrue(binary.is_file())
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for path in (ROOT / "stacks/agent-memory").glob("*.tf"):
                if path.name != "backend.generated.tf":
                    shutil.copyfile(path, directory / path.name)
            config = directory / "terraformrc"
            config.write_text(
                'provider_installation {\n dev_overrides { "RedisLabs/rediscloud" = '
                + json.dumps(str(binary.parent))
                + " }\n direct {}\n}\n"
            )
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("TF_", "REDISCLOUD_", "AGENT_MEMORY_"))
            }
            env.update(
                TF_CLI_CONFIG_FILE=str(config),
                TF_IN_AUTOMATION="true",
                REDISCLOUD_ACCESS_KEY="fake",
                REDISCLOUD_SECRET_KEY="fake",
                REDISCLOUD_URL="http://127.0.0.1:1",
            )

            def run(*args):
                result = subprocess.run(
                    [terraform, *args],
                    check=False,
                    cwd=directory,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            variables = {
                "agent_memory_name": "offline-contract",
                "database_id": 123,
                "long_term_ttl_seconds": 86400,
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "credentials": {"api_key_version": 1},
                },
                "embedding": {
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "credentials": {"api_key_version": 1},
                },
                "llm_api_key": "fake-llm",
                "embedding_api_key": "fake-embedding",
                "summarization": {
                    "enabled": True,
                    "event_count": {"threshold": 20, "retain_count": 5},
                },
                "custom_memory_types": [
                    {
                        "name": "preference",
                        "description": "Durable preference",
                        "fields": [
                            {"name": "topic", "description": "Topic", "type": "str"}
                        ],
                        "extraction_strategy": {
                            "enabled": True,
                            "prompt": "Keep stable facts",
                        },
                    }
                ],
                "long_term_memory_exclusions": {
                    "enabled": True,
                    "custom_detectors": {
                        "enabled": True,
                        "detectors": [
                            {
                                "name": "account",
                                "enabled": True,
                                "matcher": {
                                    "kind": "regex",
                                    "regex": {"pattern": "ACC-[0-9]+"},
                                },
                            }
                        ],
                    },
                },
                "timeouts": {"delete": "40m"},
            }
            path = directory / "inputs.json"
            path.write_text(json.dumps(variables))
            run("init", "-backend=false", "-input=false")
            run(
                "plan",
                "-input=false",
                "-refresh=false",
                "-var-file=inputs.json",
                "-out=create.tfplan",
            )
            plan = json.loads(run("show", "-json", "create.tfplan"))
            resource = next(
                item
                for item in plan["planned_values"]["root_module"]["resources"]
                if item["type"] == "rediscloud_agent_memory"
            )
            values = resource["values"]
            self.assertIsInstance(values["llm"], list)
            self.assertIsInstance(values["summarization"], list)
            values.update(id="store-offline", status="READY")
            state = {
                "version": 4,
                "terraform_version": "1.16.7",
                "serial": 1,
                "resources": [
                    {
                        "mode": "managed",
                        "type": "rediscloud_agent_memory",
                        "name": "this",
                        "provider": 'provider["registry.terraform.io/redislabs/rediscloud"]',
                        "instances": [
                            {
                                "schema_version": resource["schema_version"],
                                "attributes": values,
                            }
                        ],
                    }
                ],
            }
            (directory / "terraform.tfstate").write_text(json.dumps(state))
            path.write_text(
                json.dumps(agent_destroy_variables(values, "offline-contract", 123))
            )
            run(
                "plan",
                "-input=false",
                "-refresh=false",
                "-destroy",
                "-var-file=inputs.json",
                "-out=delete.tfplan",
            )
            deletion = json.loads(run("show", "-json", "delete.tfplan"))
            changes = [
                item
                for item in deletion["resource_changes"]
                if item.get("mode") == "managed"
            ]
            self.assertEqual(
                [item["change"]["actions"] for item in changes], [["delete"]]
            )
            self.assertEqual(changes[0]["address"], "rediscloud_agent_memory.this")
