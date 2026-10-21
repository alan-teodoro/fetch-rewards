#!/usr/bin/env python3
"""Isolated old/new/old Terraform state test; never emits state or credentials."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid

from agent_memory_auth_probe import ControlPlane


def run_check(database_id, baseline_binary, candidate_binary, control=None):
    control = control or ControlPlane()
    prefix = "tfacc-upgrade-" + uuid.uuid4().hex[:16]
    print("State compatibility fixture: " + prefix, flush=True)
    result = {"fixture": prefix, "stages": []}
    stage = "prepare"
    intent = None
    if os.environ.get("LIVE_RESULTS_DIRECTORY"):
        intent = Path(os.environ["LIVE_RESULTS_DIRECTORY"]) / ("intent-" + prefix + ".json")
        intent.parent.mkdir(parents=True, exist_ok=True)
        intent.write_text(json.dumps({"fixture": prefix, "database_id": str(database_id), "names": [prefix], "cleanup_verified": False}))
    with tempfile.TemporaryDirectory(prefix="rediscloud-state-compatibility-") as temporary:
        root = Path(temporary)
        work = root / "terraform"
        work.mkdir(mode=0o700)
        arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
        target = platform.system().lower() + "_" + arch
        binaries = {}
        for label, source in (("baseline", baseline_binary), ("candidate", candidate_binary)):
            folder = root / label
            folder.mkdir(mode=0o700)
            binary = folder / "terraform-provider-rediscloud"
            shutil.copy2(source, binary)
            binary.chmod(0o700)
            binaries[label] = folder
            result[label + "_binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        mirror = root / "mirror/registry.terraform.io/redislabs/rediscloud/99.99.99" / target
        mirror.mkdir(parents=True)
        shutil.copy2(binaries["baseline"] / "terraform-provider-rediscloud", mirror / "terraform-provider-rediscloud_v99.99.99")
        (work / "main.tf.json").write_text(json.dumps({
            "terraform": {"required_providers": {"rediscloud": {"source": "RedisLabs/rediscloud", "version": "99.99.99"}}},
            "variable": {"ttl": {"type": "number"}},
            "resource": {
                "rediscloud_agent_memory": {"upgrade": {
                    "name": prefix, "database_id": int(database_id),
                    "short_term_ttl_seconds": "${var.ttl}", "long_term_ttl_seconds": 7776000,
                    "extraction_cadence_seconds": 300,
                }},
                "rediscloud_agent_memory_api_key": {"runtime": {
                    "store_id": "${rediscloud_agent_memory.upgrade.id}", "name": prefix + "-runtime",
                }},
            },
        }))
        env = os.environ.copy()
        for key in list(env):
            if key.startswith(("TF_LOG", "TF_ACC", "TF_REATTACH")):
                env.pop(key)
        env.update({"TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "TF_CLI_CONFIG_FILE": str(root / "terraformrc")})

        def select(label):
            (root / "terraformrc").write_text(
                'provider_installation {\n  dev_overrides {\n    "RedisLabs/rediscloud" = '
                + json.dumps(str(binaries[label])) + '\n  }\n  direct {}\n}\n'
            )

        def command(*args, allowed=(0,)):
            completed = subprocess.run(["terraform", *args], cwd=work, env=env, capture_output=True, text=True, timeout=300)
            if completed.returncode not in allowed:
                raise RuntimeError("Terraform command failed; credential-bearing output omitted")
            return completed

        def plan(ttl, expected):
            command("plan", "-input=false", "-no-color", "-detailed-exitcode", "-var", f"ttl={ttl}", "-out=reviewed.tfplan", allowed=(0, 2))
            payload = json.loads(command("show", "-json", "reviewed.tfplan").stdout)
            changes = {r["address"]: r["change"]["actions"] for r in payload.get("resource_changes", []) if r["change"]["actions"] != ["no-op"]}
            if changes != expected:
                raise RuntimeError("Plan proposed unexpected changes; no apply performed")

        def state(ttl, previous=None):
            payload = json.loads(command("show", "-json").stdout)
            resources = {r["address"]: r["values"] for r in payload["values"]["root_module"]["resources"]}
            store = resources["rediscloud_agent_memory.upgrade"]
            key = resources["rediscloud_agent_memory_api_key.runtime"]
            if store["short_term_ttl_seconds"] != ttl or store["status"] != "READY" or str(store["database_id"]) != str(database_id):
                raise RuntimeError("Store state did not converge")
            if not store["id"] or not key["id"] or not key.get("api_key") or key["store_id"] != store["id"]:
                raise RuntimeError("Store/key state is incomplete")
            identity = (store["id"], key["id"], key["api_key"])
            if previous is not None and identity != previous:
                raise RuntimeError("Store/key ID or retained runtime secret changed across provider versions")
            return identity

        identity = None
        try:
            select("baseline")
            command("init", "-input=false", "-no-color", "-backend=false", "-plugin-dir=" + str(root / "mirror"))
            stage = "baseline create"
            print("State compatibility stage: " + stage, flush=True)
            plan(86400, {"rediscloud_agent_memory.upgrade": ["create"], "rediscloud_agent_memory_api_key.runtime": ["create"]})
            command("apply", "-input=false", "-no-color", "reviewed.tfplan")
            identity = state(86400)
            result["store_id"], result["key_id"] = identity[:2]
            result["stages"].append(stage)
            select("candidate")
            stage = "candidate reads old state without changes"
            print("State compatibility stage: " + stage, flush=True)
            plan(86400, {})
            result["stages"].append(stage)
            stage = "candidate updates existing state"
            print("State compatibility stage: " + stage, flush=True)
            plan(43200, {"rediscloud_agent_memory.upgrade": ["update"]})
            command("apply", "-input=false", "-no-color", "reviewed.tfplan")
            state(43200, identity)
            plan(43200, {})
            result["stages"].append(stage)
            select("baseline")
            stage = "baseline reads candidate-written state without changes"
            print("State compatibility stage: " + stage, flush=True)
            plan(43200, {})
            result["stages"].append(stage)
            stage = "baseline rollback update"
            print("State compatibility stage: " + stage, flush=True)
            plan(86400, {"rediscloud_agent_memory.upgrade": ["update"]})
            command("apply", "-input=false", "-no-color", "reviewed.tfplan")
            state(86400, identity)
            plan(86400, {})
            result["stages"].append(stage)
        except Exception:
            print("State compatibility failed stage: " + stage, file=sys.stderr, flush=True)
            raise RuntimeError("State compatibility failed during " + stage + "; raw output omitted; reconcile the fixture prefix if cleanup fails") from None
        finally:
            select("candidate")
            cleanup_ok = True
            try:
                if (work / "terraform.tfstate").exists():
                    command("destroy", "-auto-approve", "-input=false", "-no-color", "-var", "ttl=86400")
                    if command("state", "list").stdout.strip():
                        cleanup_ok = False
                remaining = control.request("/memory-stores").get("data", [])
                if any(s.get("name") == prefix or (identity and s.get("storeId") == identity[0]) for s in remaining):
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
            if not cleanup_ok:
                raise RuntimeError("Fixture cleanup unverified; reconcile logged fixture prefix before retrying") from None
            result["cleanup_verified"] = True
            if intent:
                payload = json.loads(intent.read_text())
                payload["cleanup_verified"] = True
                intent.write_text(json.dumps(payload))
            print("State compatibility fixture cleanup verified", flush=True)
    return result


if __name__ == "__main__":
    try:
        result = run_check(os.environ["AGENT_MEMORY_TEST_DATABASE_ID"], os.environ["BASELINE_PROVIDER_BINARY"], os.environ["CANDIDATE_PROVIDER_BINARY"])
        print(json.dumps(result, sort_keys=True))
        print("PASS: old/new/old state reads and updates preserve store/key IDs and runtime secret; fixture removed")
    except Exception:
        print("FAIL: state compatibility check did not complete; raw Terraform/SDK output omitted. Reconcile the logged fixture prefix.", file=sys.stderr)
        sys.exit(1)
