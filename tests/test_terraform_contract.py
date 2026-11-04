"""Exercise the unified root with the official provider and synthetic inputs only."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.environ.get("TEST_REGISTRY_PROVIDER") or os.environ.get("MOCK_PROVIDER_BINARY"),
    "Set TEST_REGISTRY_PROVIDER=1 for offline Terraform contract checks",
)
class TerraformContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        for stack in ("deployment", "subscription", "database", "agent-memory"):
            target = self.folder / "stacks" / stack
            target.mkdir(parents=True)
            for p in (ROOT / "stacks" / stack).glob("*.tf"):
                if p.name not in {"backend.tf", "backend.generated.tf"}:
                    shutil.copyfile(p, target / p.name)
        self.directory = self.folder / "stacks/deployment"
        shutil.copyfile(
            ROOT / "stacks/deployment/.terraform.lock.hcl",
            self.directory / ".terraform.lock.hcl",
        )
        cli = self.folder / "terraformrc"
        binary = os.environ.get("MOCK_PROVIDER_BINARY")
        cli.write_text(
            'provider_installation {\n dev_overrides { "RedisLabs/rediscloud" = '
            + json.dumps(str(Path(binary).resolve().parent))
            + " }\n direct {}\n}\n"
            if binary
            else "provider_installation { direct {} }\n"
        )
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("TF_", "REDISCLOUD_", "AGENT_MEMORY_"))
        }
        self.env.update(
            TF_CLI_CONFIG_FILE=str(cli),
            TF_IN_AUTOMATION="true",
            REDISCLOUD_ACCESS_KEY="fake",
            REDISCLOUD_SECRET_KEY="fake",
            REDISCLOUD_URL="http://127.0.0.1:1",
        )
        self.binary = os.environ.get("TF_ACC_TERRAFORM_PATH") or shutil.which(
            "terraform"
        )
        self.run_tf("init", "-backend=false", "-input=false", "-lockfile=readonly")

    def run_tf(self, *args):
        r = subprocess.run(
            [self.binary, *args],
            cwd=self.directory,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def plan(self, values):
        (self.directory / "inputs.json").write_text(json.dumps(values))
        self.run_tf(
            "plan",
            "-input=false",
            "-refresh=false",
            "-var-file=inputs.json",
            "-out=plan.tfplan",
        )
        return json.loads(self.run_tf("show", "-json", "plan.tfplan"))

    def test_first_plan_handles_unknown_managed_parent_ids(self):
        p = self.plan(
            {
                "subscription": {
                    "mode": "managed",
                    "subscription_name": "offline-sub",
                    "payment_method_id": "123",
                    "public_endpoint_access": True,
                },
                "databases": {
                    "shared": {
                        "mode": "managed",
                        "database_name": "offline-db",
                        "enable_tls": True,
                        "enable_default_user": True,
                    }
                },
                "agent_memory_stores": {
                    "shopping": {
                        "mode": "managed",
                        "agent_memory_name": "offline-store",
                        "database_key": "shared",
                        "api_keys": {"runtime": {"name": "offline-runtime"}},
                    }
                },
            }
        )
        changes = {
            r["type"]: r["change"]["actions"]
            for r in p["resource_changes"]
            if r.get("mode") == "managed"
        }
        for kind in (
            "rediscloud_subscription",
            "rediscloud_subscription_database",
            "rediscloud_agent_memory",
            "rediscloud_agent_memory_api_key",
        ):
            self.assertEqual(changes[kind], ["create"])

    def test_removing_agent_from_configuration_is_a_native_deletion(self):
        values = {
            "subscription": {
                "mode": "external",
                "subscription_name": "offline-sub",
                "subscription_id": 123,
            },
            "databases": {
                "shared": {
                    "mode": "external",
                    "database_name": "offline-db",
                    "database_id": 456,
                }
            },
            "agent_memory_stores": {
                "shopping": {
                    "mode": "managed",
                    "agent_memory_name": "offline-store",
                    "database_key": "shared",
                    "short_term_ttl_seconds": 86400,
                    "long_term_ttl_seconds": 604800,
                }
            },
        }
        p = self.plan(values)
        resources = []
        for child in p["planned_values"]["root_module"].get("child_modules", []):
            for r in child.get("resources", []):
                if r.get("mode") != "managed":
                    continue
                attrs = r["values"]
                attrs["id"] = (
                    "offline-store"
                    if r["type"] == "rediscloud_agent_memory"
                    else "synthetic-validation"
                )
                if r["type"] == "rediscloud_agent_memory":
                    attrs.update(status="READY", database_id=456)
                resources.append(
                    {
                        "module": child["address"],
                        "mode": "managed",
                        "type": r["type"],
                        "name": r["name"],
                        "provider": 'provider["registry.terraform.io/'
                        + (
                            "redislabs/rediscloud"
                            if r["type"] != "terraform_data"
                            else "builtin/terraform"
                        )
                        + '"]',
                        "instances": [
                            {"schema_version": r["schema_version"], "attributes": attrs}
                        ],
                    }
                )
        # Synthetic fixture only. Delivery code never reads or reconstructs raw state.
        for r in resources:
            if r["type"] == "terraform_data":
                r["provider"] = 'provider["terraform.io/builtin/terraform"]'
        (self.directory / "terraform.tfstate").write_text(
            json.dumps(
                {
                    "version": 4,
                    "terraform_version": "1.16.7",
                    "serial": 1,
                    "resources": resources,
                }
            )
        )
        values["agent_memory_stores"] = {}
        p = self.plan(values)
        changes = [
            r
            for r in p["resource_changes"]
            if r.get("mode") == "managed" and r["change"]["actions"] != ["no-op"]
        ]
        self.assertTrue(any(r["type"] == "rediscloud_agent_memory" for r in changes))
        self.assertTrue(all(r["change"]["actions"] == ["delete"] for r in changes))
        self.assertTrue(
            all(
                r["address"].startswith('module.agent_memory["shopping"].')
                for r in changes
            )
        )

    def test_byo_credentials_do_not_become_resource_instance_keys_or_state_values(self):
        plan = self.plan(
            {
                "subscription": {
                    "mode": "external",
                    "subscription_name": "offline-sub",
                    "subscription_id": 123,
                },
                "agent_memory_stores": {
                    "shopping": {
                        "mode": "managed",
                        "agent_memory_name": "offline-store",
                        "database_id": 456,
                        "long_term_ttl_seconds": 604800,
                        "llm": {
                            "provider": "openai",
                            "model": "gpt-4o-mini",
                            "credentials": {"api_key_version": 2},
                        },
                        "embedding": {
                            "provider": "openai",
                            "model": "text-embedding-3-small",
                            "credentials": {"api_key_version": 2},
                        },
                    }
                },
                "model_api_keys": {
                    "shopping": {
                        "llm_api_key": "fake-llm-key",
                        "embedding_api_key": "fake-embedding-key",
                    }
                },
            }
        )
        resources = [
            r
            for r in plan["resource_changes"]
            if r["type"] == "rediscloud_agent_memory"
        ]
        self.assertEqual(resources[0]["change"]["actions"], ["create"])
        self.assertNotIn("fake-llm-key", json.dumps(plan["planned_values"]))
        self.assertNotIn("fake-embedding-key", json.dumps(plan["planned_values"]))
