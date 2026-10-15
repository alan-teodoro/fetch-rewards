from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib
import time
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
sys.path.insert(0, str(ROOT / "scripts"))
review_module = load_module("rediscloud_review")
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
import hashlib,json,os,pathlib,re,sys
args=sys.argv[1:]
stack=pathlib.Path(next(a.split('=',1)[1] for a in args if a.startswith('-chdir=')))
command=args[1]
backend=stack/'.mock-backend'
if command=='init':
    backend.write_text(next(a.split('key=',1)[1] for a in args if a.startswith('-backend-config=key=')))
    if os.environ.get('MOCK_OVERRIDE_LOCK') and stack.name=='agent-memory':
        lock=stack/'.terraform.lock.hcl'
        raw=lock.read_text()
        raw=re.sub(r'^provider "registry\.terraform\.io/redislabs/rediscloud" \{\n.*?^\}\n?', '', raw,flags=re.M|re.S)
        lock.write_text(raw+'\nprovider "registry.terraform.io/redislabs/rediscloud" {\n  version = "2.19.1"\n}\n')
    if os.environ.get('MOCK_REWRITE_LOCK'):
        (stack/'.terraform.lock.hcl').write_text('provider "registry.terraform.io/hashicorp/random" {\n version = "9.9.9"\n}\n' if os.environ['MOCK_REWRITE_LOCK']=='random' else 'unapproved dependency change')
    sys.exit(0)
key=backend.read_text()
kind=stack.name
if command=='state':
    if key not in json.loads(os.environ.get('MOCK_EMPTY_STATES','[]')): print('managed.example')
    sys.exit(0)
if command=='plan':
    variables=pathlib.Path(next(a.split('=',1)[1] for a in args if a.startswith('-var-file=')))
    variables_hash=hashlib.sha256(variables.read_bytes()).hexdigest()
    fixtures=json.loads(os.environ['MOCK_CHANGES'])
    resource_type={'subscription':'rediscloud_subscription','database':'rediscloud_subscription_database','agent-memory':'rediscloud_agent_memory'}[kind]
    override=fixtures.get(key,fixtures.get(kind,{}))
    actions=['delete'] if '-destroy' in args else override.get('actions',['no-op'])
    before=override.get('before','existing')
    after=override.get('after','existing')
    before=before if isinstance(before,dict) else {'name':before}
    after=after if isinstance(after,dict) else {'name':after}
    plan={'state_key':key,'resource_changes':[{'mode':'managed','type':resource_type,'address':resource_type+'.this','change':{'actions':actions,'before':before,'after':after,'after_unknown':override.get('after_unknown',{}),'before_sensitive':override.get('before_sensitive',{}),'after_sensitive':override.get('after_sensitive',{})}}], 'output_changes':override.get('output_changes',{})}
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
    f.write(json.dumps({'command':command,'kind':kind,'state_key':key,**({'variables_hash':variables_hash} if command=='plan' else {})})+'\n')
if command=='apply' and os.environ.get('MOCK_FAIL_APPLY')==kind: sys.exit(2)
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


MOCK_AWS = r'''#!/usr/bin/env python3
import os,pathlib,shutil,sys
args=sys.argv[1:]
command=args[1]
key=args[args.index('--key')+1]
path=pathlib.Path(os.environ['MOCK_S3'])/key
if command=='put-object':
    assert args[args.index('--server-side-encryption')+1]=='AES256'
    path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(args[args.index('--body')+1],path)
elif command=='get-object':
    shutil.copyfile(path,args[-1])
elif command=='delete-object':
    path.unlink(missing_ok=True)
else:raise SystemExit('Unsupported AWS mock')
'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        for kind in ("subscription","database","agent-memory"):
            directory=self.work/"stacks"/kind
            directory.mkdir(parents=True)
            (directory/".terraform.lock.hcl").write_text("# test provider lock")
        (self.work/"scripts").mkdir()
        for source in (ROOT/"scripts").glob("rediscloud*.py"):
            shutil.copy(source,self.work/"scripts")
        binary=self.work/"bin";binary.mkdir()
        for name,source in (("terraform",MOCK_TERRAFORM),("aws",MOCK_AWS)):
            target=binary/name;target.write_text(source);target.chmod(0o755)
        provider=self.work/"provider";provider.write_text("test-provider-binary")
        self.env={**os.environ,"PATH":str(binary)+os.pathsep+os.environ["PATH"],
            "TF_STATE_BUCKET_NAME":"test-bucket","TF_STATE_REGION_NAME":"us-east-1",
            "RUNNER_TEMP":str(self.work),"GITHUB_WORKSPACE":str(self.work),
            "GITHUB_STEP_SUMMARY":str(self.work/"summary.md"),"GITHUB_OUTPUT":str(self.work/"output"),
            "GITHUB_SHA":"a"*40,"GITHUB_RUN_ID":"123","GITHUB_RUN_ATTEMPT":"1",
            "GITHUB_SERVER_URL":"https://github.com","GITHUB_REPOSITORY":"example/test",
            "TF_VERSION":"1.15.3","RESOLVED_PROVIDER_REF":"b"*40,
            "PROVIDER_BINARY":str(provider),"MOCK_EVENTS":str(self.work/"events.jsonl"),
            "MOCK_CHANGES":"{}","MOCK_S3":str(self.work/"s3")}
        self.render=self.work/".generated/rediscloud/test"
        self.config=self.work/"config.json";self.config.write_text(CONFIG_PATH.read_text())
        self.render_config()

    def render_config(self,destroy=False,key=None):
        self.manifest=config_module.render(self.config,self.render,destroy=destroy,agent_memory_key=key)
        for item in [self.manifest["subscription"],*self.manifest["databases"],*self.manifest["agent_memory_stores"]]:
            if "tfvars_path" in item:item["tfvars_path"]=str(Path(item["tfvars_path"]).relative_to(self.work))
        self.manifest["config_path"]="configs/fetch-rewards/subscriptions/test.json"
        (self.render/"manifest.json").write_text(json.dumps(self.manifest))

    def execute(self,command,phase,**options):
        Path(self.env["GITHUB_OUTPUT"]).write_text("")
        args=[sys.executable,"scripts/rediscloud_review.py",command,"--phase",phase,
              "--bundle",str(self.work/("bundle-"+phase))]
        if command=="plan":args += ["--manifest",str(self.render/"manifest.json")]
        for key,value in options.items():args += ["--"+key,str(value)]
        result=subprocess.run(args,cwd=self.work,env=self.env,capture_output=True,text=True)
        self.outputs=dict(line.split("=",1) for line in Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        return result

    def events(self):
        path=Path(self.env["MOCK_EVENTS"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def summary(self):
        path=Path(self.env["GITHUB_STEP_SUMMARY"])
        return path.read_text() if path.exists() else ""

    def approved_apply(self,phase):
        # Model the job boundary: plan -> reviewer approval -> download -> apply.
        key,sha=self.outputs["bundle_key"],self.outputs["bundle_sha256"]
        shutil.rmtree(self.work/("bundle-"+phase))
        result=self.execute("load",phase,key=key,sha256=sha)
        self.assertEqual(result.returncode,0,result.stderr)
        if self.outputs["provider_binary"]:self.env["PROVIDER_BINARY"]=self.outputs["provider_binary"]
        return self.execute("apply",phase)

    def test_fresh_plan_skips_missing_dependencies(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscription":{"actions":["create"]}})
        result=self.execute("plan","preview")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([e["kind"] for e in self.events()],["subscription"])
        self.assertIn("Skipped in plan-only mode",self.summary())

    def test_existing_managed_resources_are_all_planned(self):
        result=self.execute("plan","preview")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([e["kind"] for e in self.events()],["subscription","database","agent-memory","agent-memory"])
        self.assertNotIn("Skipped",self.summary())
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_new_database_skips_agents_but_keeps_subscription_plan(self):
        self.env["MOCK_CHANGES"]=json.dumps({"database":{"actions":["create"]}})
        self.assertEqual(self.execute("plan","preview").returncode,0)
        self.assertEqual([e["kind"] for e in self.events()],["subscription","database"])

    def test_subscription_rename_skips_downstream_name_lookups(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscription":{"actions":["update"],"after":"renamed"}})
        self.assertEqual(self.execute("plan","preview").returncode,0)
        self.assertEqual([e["kind"] for e in self.events()],["subscription"])

    def test_apply_plans_entire_phase_then_applies_saved_plans_without_replanning(self):
        self.env["MOCK_CHANGES"]=json.dumps({kind:{"actions":["create"]} for kind in ("subscription","database","agent-memory")})
        for phase in ("subscription","database","agent-memory"):
            result=self.execute("plan",phase)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(self.outputs["needs_apply"],"true")
            result=self.approved_apply(phase)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([(e["command"],e["kind"]) for e in self.events()],[
            ("plan","subscription"),("apply","subscription"),("plan","database"),("apply","database"),
            ("plan","agent-memory"),("plan","agent-memory"),("apply","agent-memory"),("apply","agent-memory")])

    def test_no_changes_requests_no_approval_or_bundle(self):
        self.assertEqual(self.execute("plan","agent-memory").returncode,0)
        self.assertEqual(self.outputs,{"needs_apply":"false"})
        self.assertFalse((self.work/"s3").exists())

    def test_destructive_agent_plan_blocks_entire_phase_before_upload(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate":{"actions":["delete","create"]}})
        result=self.execute("plan","agent-memory")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Use the Redis Cloud Config Destroy workflow",result.stderr)
        self.assertFalse((self.work/"s3").exists())
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_selective_destroy_only_applies_selected_state(self):
        self.render_config(destroy=True,key="support_agent")
        self.assertEqual(self.execute("plan","destroy").returncode,0)
        result=self.approved_apply("destroy")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([e["state_key"] for e in self.events()],["subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate"]*2)

    def test_full_destroy_plans_all_before_approval_and_reverses_dependencies(self):
        self.render_config(destroy=True)
        result=self.execute("plan","destroy")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(all(e["command"]=="plan" for e in self.events()))
        result=self.approved_apply("destroy")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([e["kind"] for e in self.events() if e["command"]=="apply"],["agent-memory","agent-memory","database","subscription"])

    def test_empty_destroy_state_skips_remote_lookups_and_approval(self):
        self.render_config(destroy=True,key="support_agent")
        self.env["MOCK_EMPTY_STATES"]=json.dumps(["subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate"])
        self.assertEqual(self.execute("plan","destroy").returncode,0)
        self.assertEqual(self.outputs["needs_apply"],"false")
        self.assertEqual(self.events(),[])

    def prepare_changed_phase(self):
        self.env["MOCK_CHANGES"]=json.dumps({"agent-memory":{"actions":["update"]}})
        result=self.execute("plan","agent-memory")
        self.assertEqual(result.returncode,0,result.stderr)

    def test_tampered_archive_is_rejected_before_apply(self):
        self.prepare_changed_phase()
        key=self.outputs["bundle_key"];sha=self.outputs["bundle_sha256"]
        (Path(self.env["MOCK_S3"])/key).write_bytes(b"tampered")
        result=self.execute("load","agent-memory",key=key,sha256=sha)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("checksum mismatch",result.stderr)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_expired_or_wrong_run_bundle_is_rejected_before_any_apply(self):
        self.prepare_changed_phase()
        index=self.work/"bundle-agent-memory/index.json";original=json.loads(index.read_text())
        for field,value in (("created",0),("run_id","different"),("attempt","2"),("commit","different"),("phase","database")):
            with self.subTest(field=field):
                changed=deepcopy(original);changed[field]=value;index.write_text(json.dumps(changed))
                self.assertNotEqual(self.execute("apply","agent-memory").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_tampering_with_later_plan_stops_all_applies(self):
        self.prepare_changed_phase()
        bundle=self.work/"bundle-agent-memory"
        index=json.loads((bundle/"index.json").read_text())
        (bundle/index["plans"][-1]["file"]).write_text("tampered")
        self.assertNotEqual(self.execute("apply","agent-memory").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_wrong_active_provider_is_rejected(self):
        self.prepare_changed_phase()
        wrong=self.work/"wrong-provider";wrong.write_text("another binary")
        self.env["PROVIDER_BINARY"]=str(wrong)
        self.assertNotEqual(self.execute("apply","agent-memory").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_dependency_change_during_apply_init_is_rejected(self):
        self.prepare_changed_phase()
        self.env["MOCK_REWRITE_LOCK"]="1"
        result=self.execute("apply","agent-memory")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Provider dependencies changed after approval",result.stderr)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_multiple_agents_tolerate_ignored_registry_lock_rewrite(self):
        self.env["MOCK_CHANGES"]=json.dumps({"agent-memory":{"actions":["update"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        index=json.loads((self.work/"bundle-rollout/index.json").read_text())
        agent_locks=[item for item in index["plans"] if item["stack"]=="agent-memory"]
        self.env["MOCK_OVERRIDE_LOCK"]="1"
        result=self.approved_apply("rollout")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len([e for e in self.events() if e["command"]=="apply" and e["kind"]=="agent-memory"]),2)
        final_lock=self.work/"stacks/agent-memory/.terraform.lock.hcl"
        self.assertEqual(hashlib.sha256(final_lock.read_bytes()).hexdigest(),agent_locks[-1]["lock_sha256"])

    def test_registry_mode_rejects_rediscloud_lock_change(self):
        self.env.pop("PROVIDER_BINARY")
        self.prepare_changed_phase()
        self.env["MOCK_OVERRIDE_LOCK"]="1"
        self.assertNotEqual(self.approved_apply("agent-memory").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_override_does_not_allow_random_provider_change(self):
        self.prepare_changed_phase()
        self.env["MOCK_OVERRIDE_LOCK"]="1"
        self.env["MOCK_REWRITE_LOCK"]="random"
        self.assertNotEqual(self.execute("apply","agent-memory").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_summary_omits_secret_and_sensitive_values(self):
        marker="DO-NOT-PRINT-THIS-SECRET"
        self.env["MOCK_CHANGES"]=json.dumps({"agent-memory":{"actions":["update"],
            "before":{"name":"old","short_term_ttl_seconds":1,"api_key":marker},
            "after":{"name":marker,"short_term_ttl_seconds":2,"api_key":marker,"llm":{"credentials":marker}},
            "after_sensitive":{"name":True},"output_changes":{"api_key":{"actions":["update"],"after":marker}}}})
        result=self.execute("plan","agent-memory")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn(marker,self.summary())
        self.assertIn("short_term_ttl_seconds",self.summary())
        self.assertIn("Approval required",self.summary())

    def test_single_approval_fresh_rollout_freezes_deferred_inputs(self):
        self.env["MOCK_CHANGES"]=json.dumps({kind:{"actions":["create"]} for kind in ("subscription","database","agent-memory")})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.assertEqual(self.outputs["needs_apply"],"true")
        self.assertEqual([e["kind"] for e in self.events()],["subscription"])
        self.assertIn("One approval for the full configuration",self.summary())
        self.assertIn("/blob/"+self.env["GITHUB_SHA"]+"/configs/fetch-rewards/subscriptions/test.json",self.summary())
        self.assertEqual(self.summary().count("## Deferred plan:"),3)
        index=json.loads((self.work/"bundle-rollout/index.json").read_text())
        hashes=[item["variables_sha256"] for item in index["plans"] if item.get("deferred")]
        for item in [*self.manifest["databases"],*self.manifest["agent_memory_stores"]]:
            (self.work/item["tfvars_path"]).write_text("changed after approval")
        result=self.approved_apply("rollout")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([(e["command"],e["kind"]) for e in self.events()],[
            ("plan","subscription"),("apply","subscription"),("plan","database"),("apply","database"),
            ("plan","agent-memory"),("plan","agent-memory"),("apply","agent-memory"),("apply","agent-memory")])
        self.assertEqual([e["variables_hash"] for e in self.events()[1:] if e["command"]=="plan"],hashes)

    def test_existing_rollout_reuses_all_reviewed_plans(self):
        self.env["MOCK_CHANGES"]=json.dumps({"agent-memory":{"actions":["update"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.assertEqual(len(self.events()),4)
        self.assertNotIn("## Deferred plan:",self.summary())
        self.assertEqual(self.approved_apply("rollout").returncode,0)
        self.assertEqual([e["command"] for e in self.events()],["plan"]*4+["apply"]*4)

    def test_unchanged_rollout_needs_no_approval(self):
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.assertEqual(self.outputs,{"needs_apply":"false"})
        self.assertFalse((self.work/"s3").exists())

    def test_deferred_inputs_tampering_rejects_all_applies(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscription":{"actions":["create"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        bundle=self.work/"bundle-rollout"
        index=json.loads((bundle/"index.json").read_text())
        item=next(item for item in index["plans"] if item.get("deferred"))
        (bundle/item["variables"]).write_text("tampered")
        self.assertNotEqual(self.execute("apply","rollout").returncode,0)
        self.assertFalse(any(e["command"]=="apply" for e in self.events()))

    def test_deferred_replacement_stops_every_agent_apply(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscription":{"actions":["create"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.env["MOCK_CHANGES"]=json.dumps({"subscriptions/demo-ai-us-east-1/agent-memory/support_agent.tfstate":{"actions":["delete","create"]}})
        result=self.approved_apply("rollout")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Deferred plan would delete or replace",result.stderr)
        self.assertFalse(any(e["command"]=="apply" and e["kind"]=="agent-memory" for e in self.events()))

    def test_rollout_stops_on_apply_failure(self):
        self.env["MOCK_CHANGES"]=json.dumps({"subscription":{"actions":["create"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.env["MOCK_FAIL_APPLY"]="subscription"
        self.assertNotEqual(self.approved_apply("rollout").returncode,0)
        self.assertEqual([e["kind"] for e in self.events()],["subscription","subscription"])

    def test_rollout_with_new_database_defers_only_its_agents(self):
        self.env["MOCK_CHANGES"]=json.dumps({"database":{"actions":["create"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.assertEqual([e["kind"] for e in self.events()],["subscription","database"])
        self.assertEqual(self.summary().count("## Deferred plan:"),2)
        self.assertEqual(self.approved_apply("rollout").returncode,0)

    def test_mixed_rollout_reviews_ready_agents_and_defers_only_new_database_agent(self):
        config=json.loads(self.config.read_text())
        config["databases"]["new_database"]=deepcopy(next(iter(config["databases"].values())))
        config["databases"]["new_database"]["name"]="new-database"
        config["agent_memory_stores"]["support_agent"]["database"]="new_database"
        self.config.write_text(json.dumps(config));self.render_config()
        new_database=next(item for item in self.manifest["databases"] if item["key"]=="new_database")
        self.env["MOCK_CHANGES"]=json.dumps({new_database["state_key"]:{"actions":["create"]}})
        self.assertEqual(self.execute("plan","rollout").returncode,0)
        self.assertEqual(self.summary().count("## Deferred plan:"),1)
        reviewed=[e["state_key"] for e in self.events()]
        shopping=next(item for item in self.manifest["agent_memory_stores"] if item["key"]=="shopping_agent")
        support=next(item for item in self.manifest["agent_memory_stores"] if item["key"]=="support_agent")
        self.assertIn(shopping["state_key"],reviewed)
        self.assertNotIn(support["state_key"],reviewed)
        self.assertEqual(self.approved_apply("rollout").returncode,0)
        self.assertEqual(len([e for e in self.events() if e["command"]=="plan" and e["state_key"]==shopping["state_key"]]),1)

    def test_single_gate_depends_on_full_configuration_review(self):
        source=(ROOT/".github/workflows/rediscloud-phase.yml").read_text()
        self.assertIn("needs: plan",source)
        self.assertIn("if: inputs.apply && needs.plan.outputs.needs_apply == 'true'",source)
        apply=source.split("\n  apply:\n",1)[1]
        self.assertIn("environment:",apply)
        self.assertIn("rediscloud_review.py apply",apply)
        self.assertNotIn("rediscloud_review.py plan",apply)
        config=(ROOT/".github/workflows/rediscloud-config.yml").read_text()
        self.assertNotIn("always()",config)
        self.assertEqual(config.count("apply: true"),1)
        self.assertIn("phase: rollout",config)
        self.assertNotIn("needs: subscription",config)


if __name__ == "__main__":
    unittest.main()
