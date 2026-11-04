"""JSON mapping and saved-plan workflow regressions, without cloud operations."""

import hashlib
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
from rediscloud import config as configuration
from rediscloud.config_common import ConfigError, read_json
from rediscloud.lifecycle import validate_plan

FIXTURE = ROOT / "tests/fixtures/configs/two-agents.json"


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "config.json"
        self.path.write_text(FIXTURE.read_text())

    def render(self, **kwargs):
        return configuration.render(self.path, self.folder / "render", **kwargs)

    def values(self, m):
        return json.loads(Path(m["deployment"]["tfvars_path"]).read_text())

    def test_one_json_has_one_state_and_one_tfvars_file(self):
        m = self.render()
        self.assertEqual(
            m["deployment"]["state_key"],
            "subscriptions/demo-ai-us-east-1/terraform.tfstate",
        )
        self.assertEqual(
            len(list((self.folder / "render").glob("*.auto.tfvars.json"))), 1
        )
        self.assertEqual(len(self.values(m)["agent_memory_stores"]), 2)

    def test_keys_and_external_database_ids_are_preserved(self):
        c = json.loads(self.path.read_text())
        db = next(iter(c["databases"].values()))
        db.update(mode="external", database_id=123)
        self.path.write_text(json.dumps(c))
        v = self.values(self.render())
        self.assertEqual(next(iter(v["databases"].values()))["database_id"], 123)
        self.assertEqual(set(v["agent_memory_stores"]), set(c["agent_memory_stores"]))

    def test_selective_destroy_keeps_parents_and_other_agents(self):
        original = json.loads(self.path.read_text())
        m = self.render(destroy=True, agent_memory_key="support_agent")
        v = self.values(m)
        self.assertEqual(v["subscription"]["mode"], "managed")
        self.assertEqual(len(v["databases"]), 1)
        self.assertEqual(set(v["agent_memory_stores"]), {"shopping_agent"})
        self.assertEqual(m["selected_module"], 'module.agent_memory["support_agent"]')
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_unknown_or_external_destroy_target_is_rejected(self):
        with self.assertRaises(ConfigError):
            self.render(destroy=True, agent_memory_key="missing")
        c = json.loads(self.path.read_text())
        c["agent_memory_stores"]["shopping_agent"]["mode"] = "external"
        self.path.write_text(json.dumps(c))
        with self.assertRaises(ConfigError):
            self.render(destroy=True, agent_memory_key="shopping_agent")

    def test_duplicate_keys_and_unsafe_paths_are_rejected(self):
        self.path.write_text('{"a":1,"a":2}')
        with self.assertRaises(ConfigError):
            read_json(self.path)
        for p in ("../outside.json", "/tmp/config.json", "tests/config.json"):
            with self.assertRaises(ConfigError):
                configuration.validate_workflow_path(Path(p))

    def test_removing_referenced_database_is_rejected_before_terraform(self):
        c = json.loads(self.path.read_text())
        c["databases"] = {}
        self.path.write_text(json.dumps(c))
        with self.assertRaisesRegex(ConfigError, "unknown database"):
            self.render()

    def test_model_credentials_are_separate_from_for_each_identities(self):
        c = json.loads(self.path.read_text())
        s = c["agent_memory_stores"]["shopping_agent"]
        s["llm"] = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "credentials": {"api_key_env_var": "TEST_LLM_KEY", "api_key_version": 2},
        }
        s["embedding"] = {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "credentials": {"api_key_env_var": "TEST_EMBED_KEY", "api_key_version": 2},
        }
        self.path.write_text(json.dumps(c))
        from unittest.mock import patch

        with patch.dict(
            os.environ, {"TEST_LLM_KEY": "fake-llm", "TEST_EMBED_KEY": "fake-embedding"}
        ):
            v = self.values(self.render())
        self.assertEqual(
            v["model_api_keys"]["shopping_agent"]["llm_api_key"], "fake-llm"
        )
        self.assertNotIn("llm_api_key", v["agent_memory_stores"]["shopping_agent"])
        self.assertEqual(
            v["agent_memory_stores"]["shopping_agent"]["llm"]["credentials"][
                "api_key_version"
            ],
            2,
        )

    def test_example_configuration_is_valid(self):
        path = ROOT / "configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json"
        config = configuration.load_and_validate(path)
        self.assertEqual(len(config["agent_memory_stores"]), 1)
        manifest = configuration.render(path, self.folder / "example")
        self.assertEqual(
            set(self.values(manifest)["agent_memory_stores"]), {"shopping_agent"}
        )

    def test_null_optional_collections_render_as_empty_maps(self):
        config = json.loads(self.path.read_text())
        config.update(databases=None, agent_memory_stores=None)
        self.path.write_text(json.dumps(config))
        values = self.values(self.render())
        self.assertEqual(values["databases"], {})
        self.assertEqual(values["agent_memory_stores"], {})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        d = self.work / "stacks/deployment"
        d.mkdir(parents=True)
        (d / ".terraform.lock.hcl").write_text("reviewed dependencies")
        shutil.copytree(
            ROOT / "scripts",
            self.work / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copytree(ROOT / "schemas", self.work / "schemas")
        b = self.work / "bin"
        b.mkdir()
        for name in ("aws", "terraform"):
            p = b / name
            shutil.copyfile(ROOT / f"tests/fakes/{name}.py", p)
            p.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(b) + os.pathsep + os.environ["PATH"],
            "TF_STATE_BUCKET_NAME": "test-bucket",
            "TF_STATE_REGION_NAME": "us-east-1",
            "RUNNER_TEMP": str(self.work),
            "GITHUB_STEP_SUMMARY": str(self.work / "summary.md"),
            "GITHUB_OUTPUT": str(self.work / "output"),
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "example/test",
            "TF_VERSION": "1.16.7",
            "MOCK_EVENTS": str(self.work / "events"),
            "MOCK_CHANGES": "{}",
            "MOCK_S3": str(self.work / "s3"),
        }
        path = self.work / "config.json"
        path.write_text(FIXTURE.read_text())
        self.manifest = configuration.render(path, self.work / "render")
        self.manifest_path = self.work / "render/manifest.json"
        self.bundle = self.work / "bundle"

    def execute(self, command, phase="rollout", **options):
        self.env.update(options)
        Path(self.env["GITHUB_OUTPUT"]).write_text("")
        self.manifest_path.write_text(json.dumps(self.manifest))
        args = [
            sys.executable,
            "scripts/rediscloud_review.py",
            command,
            "--phase",
            phase,
            "--bundle",
            str(self.bundle),
        ]
        if command == "plan":
            args += ["--manifest", str(self.manifest_path)]
        if command == "load":
            args += ["--key", self.key, "--sha256", self.sha]
        r = subprocess.run(
            args, cwd=self.work, env=self.env, text=True, capture_output=True
        )
        outputs = dict(
            x.split("=", 1)
            for x in Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines()
        )
        if "bundle_key" in outputs:
            self.key = outputs["bundle_key"]
            self.sha = outputs["bundle_sha256"]
        return r

    def changed(self):
        r = self.execute("plan", MOCK_CHANGES=json.dumps({"actions": ["update"]}))
        self.assertEqual(r.returncode, 0, r.stderr)

    def events(self):
        p = Path(self.env["MOCK_EVENTS"])
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_fresh_plan_includes_complete_root_without_deferred_plans(self):
        r = self.execute(
            "plan", "preview", MOCK_CHANGES=json.dumps({"actions": ["create"]})
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(
            self.events()[0]["state_key"],
            "subscriptions/demo-ai-us-east-1/terraform.tfstate",
        )
        self.assertNotIn("Deferred", Path(self.env["GITHUB_STEP_SUMMARY"]).read_text())

    def test_saved_plan_is_applied_without_replanning(self):
        self.changed()
        self.assertEqual(self.execute("load").returncode, 0)
        r = self.execute("apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([e["command"] for e in self.events()], ["plan", "apply"])

    def test_unchanged_configuration_needs_no_approval_or_bundle(self):
        r = self.execute("plan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.bundle.with_suffix(".tar.gz").exists())
        self.assertIn("needs_apply=false", Path(self.env["GITHUB_OUTPUT"]).read_text())

    def test_tampered_archive_is_rejected(self):
        self.changed()
        (Path(self.env["MOCK_S3"]) / self.key).write_text("tampered")
        self.assertNotEqual(self.execute("load").returncode, 0)

    def test_tampered_plan_is_rejected_before_apply(self):
        self.changed()
        (self.bundle / "review.tfplan").write_text("tampered")
        self.assertNotEqual(self.execute("apply").returncode, 0)
        self.assertEqual(len(self.events()), 1)

    def test_expired_wrong_run_and_backend_are_rejected(self):
        self.changed()
        p = self.bundle / "index.json"
        baseline = json.loads(p.read_text())
        for field, value in (
            ("created", 0),
            ("commit", "other"),
            ("run_id", "other"),
            ("attempt", "2"),
            ("state_bucket", "other"),
            ("state_region", "other"),
            ("deployment_environment", "other"),
            ("terraform_version", "other"),
        ):
            with self.subTest(field=field):
                p.write_text(json.dumps({**baseline, field: value}))
                self.assertNotEqual(self.execute("apply").returncode, 0)
        self.assertEqual(len(self.events()), 1)

    def test_dependency_changes_are_rejected_before_apply(self):
        self.changed()
        self.assertNotEqual(self.execute("apply", MOCK_REWRITE_LOCK="1").returncode, 0)
        self.assertEqual(len(self.events()), 1)

    def test_apply_failure_is_reported_without_a_success_summary(self):
        self.changed()
        r = self.execute("apply", MOCK_FAIL_APPLY="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(
            "plan applied", Path(self.env["GITHUB_STEP_SUMMARY"]).read_text()
        )

    def test_sensitive_values_are_not_published_in_summary(self):
        marker = "DO-NOT-PRINT-SECRET"
        r = self.execute(
            "plan",
            MOCK_CHANGES=json.dumps(
                {
                    "actions": ["update"],
                    "before": {"name": "old", "api_key": marker},
                    "after": {
                        "name": marker,
                        "api_key": marker,
                        "short_term_ttl_seconds": 2,
                    },
                    "after_sensitive": {"name": True},
                }
            ),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(marker, Path(self.env["GITHUB_STEP_SUMMARY"]).read_text())

    def test_retained_agent_cannot_reference_deleted_database(self):
        p = {
            "resource_changes": [
                {
                    "mode": "managed",
                    "type": "rediscloud_subscription_database",
                    "address": 'module.database["db"].rediscloud_subscription_database.this',
                    "change": {
                        "actions": ["delete"],
                        "before": {"db_id": 123},
                        "after": None,
                    },
                },
                {
                    "mode": "managed",
                    "type": "rediscloud_agent_memory",
                    "address": 'module.agent_memory["agent"].rediscloud_agent_memory.this',
                    "change": {"actions": ["no-op"], "after": {"database_id": 123}},
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "retained Agent Memory"):
            validate_plan(p, self.manifest)

    def test_external_ownership_transfer_requires_explicit_reconciliation(self):
        self.manifest["databases"][0]["mode"] = "external"
        key = self.manifest["databases"][0]["key"]
        p = {
            "resource_changes": [
                {
                    "mode": "managed",
                    "type": "rediscloud_subscription_database",
                    "address": f'module.database["{key}"].rediscloud_subscription_database.this',
                    "change": {"actions": ["delete"], "before": {"db_id": 123}},
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "ownership transfer"):
            validate_plan(p, self.manifest)

    def test_selective_destroy_rejects_unrelated_changes(self):
        self.manifest["selected_module"] = 'module.agent_memory["support_agent"]'
        p = {
            "resource_changes": [
                {
                    "mode": "managed",
                    "type": "rediscloud_agent_memory",
                    "address": 'module.agent_memory["shopping_agent"].rediscloud_agent_memory.this',
                    "change": {"actions": ["delete"], "before": {}},
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "Selective destroy"):
            validate_plan(p, self.manifest)

    def test_unsafe_archive_members_are_rejected(self):
        import io
        import tarfile

        self.changed()
        archive = self.work / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            entry = tarfile.TarInfo("../outside")
            entry.size = 1
            stream.addfile(entry, io.BytesIO(b"x"))
        shutil.copyfile(archive, Path(self.env["MOCK_S3"]) / self.key)
        self.sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        result = self.execute("load")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid review bundle", result.stderr)
        self.assertFalse((self.work / "outside").exists())

    def test_changed_state_key_is_rejected_before_apply(self):
        self.changed()
        path = self.bundle / "index.json"
        index = json.loads(path.read_text())
        index["state_key"] = "subscriptions/another/terraform.tfstate"
        path.write_text(json.dumps(index))
        self.assertNotEqual(self.execute("apply").returncode, 0)
        self.assertEqual(len(self.events()), 1)

    def test_selective_destroy_accepts_only_selected_module_deletions(self):
        self.manifest["selected_module"] = 'module.agent_memory["support_agent"]'
        plan = {
            "resource_changes": [
                {
                    "mode": "managed",
                    "type": "rediscloud_agent_memory",
                    "address": 'module.agent_memory["support_agent"].rediscloud_agent_memory.this',
                    "change": {"actions": ["delete"], "before": {"database_id": 123}},
                }
            ]
        }
        validate_plan(plan, self.manifest)
