from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config_module = load_module("rediscloud_config")
plan_module = load_module("rediscloud_plan")
CONFIG_PATH = ROOT / "configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json"


def change(resource_type, actions, before="existing", after="existing"):
    return {"mode": "managed", "type": resource_type, "change": {
        "actions": actions, "before": {"name": before}, "after": {"name": after}, "after_unknown": {},
    }}


def workflow_script(filename, step):
    source = (ROOT / ".github/workflows" / filename).read_text()
    section = source.split(f"      - name: {step}\n", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(section.split("        run: |\n", 1)[1])


MOCK_TERRAFORM = r'''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
stack=pathlib.Path(next(a.split('=',1)[1] for a in args if a.startswith('-chdir=')))
command=args[1]
backend=stack/'.mock-backend'
if command=='init':
    backend.write_text(next(a.split('key=',1)[1] for a in args if a.startswith('-backend-config=key=')))
    sys.exit(0)
key=backend.read_text()
kind=stack.name
if command=='plan':
    fixtures=json.loads(os.environ['MOCK_CHANGES'])
    resource_type={'subscription':'rediscloud_subscription','database':'rediscloud_subscription_database','agent-memory':'rediscloud_agent_memory'}[kind]
    override=fixtures.get(key,fixtures.get(kind,{}))
    actions=['delete'] if '-destroy' in args else override.get('actions',['no-op'])
    before={'name':override.get('before','existing')}
    after={'name':override.get('after','existing')}
    plan={'state_key':key,'resource_changes':[{'mode':'managed','type':resource_type,'address':resource_type+'.this','change':{'actions':actions,'before':before,'after':after,'after_unknown':{}}}]}
    name=next(a.split('=',1)[1] for a in args if a.startswith('-out='))
    (stack/name).write_text(json.dumps(plan))
elif command=='show':
    print((stack/args[-1]).read_text())
    sys.exit(0)
elif command=='apply':
    key=json.loads((stack/args[-1]).read_text())['state_key']
else:
    raise SystemExit('Unsupported mock command: '+command)
with open(os.environ['MOCK_EVENTS'],'a') as f:
    f.write(json.dumps({'command':command,'kind':kind,'state_key':key})+'\n')
'''


class ConfigTests(unittest.TestCase):
    def test_missing_or_empty_field_description_fails_config_validation(self):
        original = json.loads(CONFIG_PATH.read_text())
        for value in (None, "", " ", "x" * 201):
            with self.subTest(description=value), tempfile.TemporaryDirectory() as tmp:
                config = deepcopy(original)
                field = config["agent_memory_stores"]["shopping_agent"]["custom_memory_types"][0]["fields"][0]
                if value is None:
                    field.pop("description")
                else:
                    field["description"] = value
                path = Path(tmp) / "config.json"
                path.write_text(json.dumps(config))
                with self.assertRaisesRegex(config_module.ConfigError, r"fields\[0\]\.description"):
                    config_module.load_and_validate(path)

    def test_selective_destroy_preserves_original_and_targets_one_state(self):
        original = config_module.load_and_validate(CONFIG_PATH)
        before = deepcopy(original)
        selected = config_module.select_destroy_config(original, "support_agent")
        self.assertEqual(original, before)
        self.assertEqual(selected["subscription"]["mode"], "external")
        self.assertTrue(all(db["mode"] == "external" for db in selected["databases"].values()))
        self.assertEqual(list(selected["agent_memory_stores"]), ["support_agent"])
        with tempfile.TemporaryDirectory() as tmp:
            manifest = config_module.render(CONFIG_PATH, Path(tmp), destroy=True, agent_memory_key="support_agent")
            targeted = [item for item in [manifest["subscription"], *manifest["databases"], *manifest["agent_memory_stores"]] if item["mode"] == "managed"]
            self.assertEqual([item["state_key"] for item in targeted], ["subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate"])
            self.assertEqual(len(list(Path(tmp).glob("*.auto.tfvars.json"))), 1)

    def test_unknown_or_external_destroy_target_is_rejected(self):
        config = config_module.load_and_validate(CONFIG_PATH)
        with self.assertRaises(config_module.ConfigError):
            config_module.select_destroy_config(config, "typo")
        config["agent_memory_stores"]["support_agent"]["mode"] = "external"
        with self.assertRaises(config_module.ConfigError):
            config_module.select_destroy_config(config, "support_agent")

    def test_destroy_does_not_require_unrelated_model_credentials(self):
        config = json.loads(CONFIG_PATH.read_text())
        for block in ("llm", "embedding"):
            config["agent_memory_stores"]["shopping_agent"][block] = {
                "provider": "openai", "model": "placeholder",
                "credentials": {"type": "apiKey", "api_key_env_var": "MISSING_DEMO_CREDENTIAL"},
            }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(config))
            manifest = config_module.render(path, Path(tmp) / "render", destroy=True, agent_memory_key="support_agent")
            self.assertEqual(manifest["agent_memory_stores"][0]["key"], "support_agent")


class DependencyTests(unittest.TestCase):
    def test_dependency_states(self):
        for resource_type in ("rediscloud_subscription", "rediscloud_subscription_database"):
            for actions, before, after, expected in [
                (["no-op"], "existing", "existing", "ready"),
                (["update"], "existing", "existing", "ready"),
                (["update"], "existing", "renamed", "pending"),
                (["create"], "existing", "existing", "pending"),
                (["delete", "create"], "existing", "existing", "pending"),
                (["delete"], "existing", "existing", "pending"),
            ]:
                with self.subTest(resource_type=resource_type, actions=actions, after=after):
                    self.assertEqual(plan_module.dependency_status({"resource_changes": [change(resource_type, actions, before, after)]}, resource_type), expected)

    def test_unknown_name_is_pending_and_missing_dependency_is_an_error(self):
        item = change("rediscloud_subscription", ["update"])
        item["change"]["after_unknown"] = {"name": True}
        self.assertEqual(plan_module.dependency_status({"resource_changes": [item]}, item["type"]), "pending")
        with self.assertRaises(ValueError):
            plan_module.dependency_status({"resource_changes": []}, item["type"])


class WorkflowTests(unittest.TestCase):
    def run_workflow(self, operation="plan", changes=None, destroy_key=None, full_destroy=False):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for kind in ("subscription", "database", "agent-memory"):
                (work / "stacks" / kind).mkdir(parents=True)
            (work / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/rediscloud_plan.py", work / "scripts")
            binary = work / "bin"
            binary.mkdir()
            (binary / "terraform").write_text(MOCK_TERRAFORM)
            (binary / "terraform").chmod(0o755)
            # Render relative tfvars paths just as the workflow does.
            config = work / "config.json"
            config.write_text(CONFIG_PATH.read_text())
            render = work / ".generated/rediscloud/test"
            manifest = config_module.render(config, render, destroy=full_destroy or destroy_key is not None, agent_memory_key=destroy_key)
            for item in [manifest["subscription"], *manifest["databases"], *manifest["agent_memory_stores"]]:
                if "tfvars_path" in item:
                    item["tfvars_path"] = str(Path(item["tfvars_path"]).relative_to(work))
            (render / "manifest.json").write_text(json.dumps(manifest))
            event_file = work / "events.jsonl"
            env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"], "TF_STATE_BUCKET_NAME": "test-bucket", "TF_STATE_REGION_NAME": "us-east-1", "OPERATION": operation, "RENDER_DIR": ".generated/rediscloud/test", "RUNNER_TEMP": str(work), "GITHUB_WORKSPACE": str(work), "GITHUB_STEP_SUMMARY": str(work / "summary.md"), "MOCK_EVENTS": str(event_file), "MOCK_CHANGES": json.dumps(changes or {})}
            destroy = full_destroy or destroy_key is not None
            script = workflow_script("rediscloud-destroy.yml" if destroy else "rediscloud-config.yml", "Destroy rendered config" if destroy else "Plan and apply rendered config")
            result = subprocess.run(["bash", "-c", script], cwd=work, env=env, capture_output=True, text=True)
            events = [json.loads(line) for line in event_file.read_text().splitlines()] if event_file.exists() else []
            summary = (work / "summary.md").read_text() if (work / "summary.md").exists() else ""
            return result, events, summary

    def test_fresh_plan_skips_missing_dependencies(self):
        result, events, summary = self.run_workflow(changes={"subscription": {"actions": ["create"]}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in events], ["subscription"])
        self.assertIn("Skipped in plan-only mode", summary)

    def test_existing_managed_resources_are_all_planned(self):
        result, events, summary = self.run_workflow()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in events], ["subscription", "database", "agent-memory", "agent-memory"])
        self.assertNotIn("Skipped in plan-only mode", summary)
        self.assertTrue(all(event["command"] == "plan" for event in events))

    def test_new_database_skips_agents_but_keeps_subscription_plan(self):
        result, events, _ = self.run_workflow(changes={"database": {"actions": ["create"]}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in events], ["subscription", "database"])

    def test_subscription_rename_skips_downstream_name_lookups(self):
        result, events, _ = self.run_workflow(changes={"subscription": {"actions": ["update"], "after": "new-name"}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in events], ["subscription"])

    def test_apply_plans_the_entire_agent_phase_before_applying(self):
        result, events, _ = self.run_workflow(operation="apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(event["command"], event["kind"]) for event in events], [
            ("plan", "subscription"), ("apply", "subscription"), ("plan", "database"), ("apply", "database"),
            ("plan", "agent-memory"), ("plan", "agent-memory"), ("apply", "agent-memory"), ("apply", "agent-memory"),
        ])
        memory_states = [event["state_key"] for event in events if event["kind"] == "agent-memory" and event["command"] == "apply"]
        self.assertEqual(len(set(memory_states)), 2)

    def test_destructive_agent_plan_blocks_all_agent_applies(self):
        result, events, _ = self.run_workflow(operation="apply", changes={"subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate": {"actions": ["delete", "create"]}})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(event["kind"] == "agent-memory" and event["command"] == "apply" for event in events))
        self.assertIn("Use the Redis Cloud Config Destroy workflow", result.stderr)

    def test_selective_destroy_only_applies_selected_agent_state(self):
        result, events, _ = self.run_workflow(destroy_key="support_agent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["state_key"] for event in events], ["subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate"] * 2)

    def test_full_destroy_reverses_dependencies(self):
        result, events, _ = self.run_workflow(full_destroy=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in events if event["command"] == "apply"], ["agent-memory", "agent-memory", "database", "subscription"])


if __name__ == "__main__":
    unittest.main()
