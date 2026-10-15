#!/usr/bin/env python3
"""Review Terraform changes, then execute the approved encrypted bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from rediscloud_plan import dependency_status


STACKS = {"subscription", "database", "agent-memory"}
PUBLIC_FIELDS = {
    "rediscloud_subscription": {"name", "public_endpoint_access", "memory_storage"},
    "rediscloud_subscription_database": {"name", "dataset_size_in_gb", "throughput_measurement_value", "alerts", "enable_tls", "enable_default_user"},
    "rediscloud_agent_memory": {"name", "database_id", "short_term_ttl_seconds", "long_term_ttl_seconds", "extraction_cadence_seconds"},
}


def run(*args: str, capture=False):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None).stdout


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output(key, value):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"{key}={value}\n")


def summary(text):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
        stream.write(text + "\n")


def cell(value):
    return str(value).replace("|", "&#124;").replace("\n", " ").replace("`", "&#96;")


def protected(value):
    if isinstance(value, dict):
        return any(protected(item) for item in value.values())
    if isinstance(value, list):
        return any(protected(item) for item in value)
    return value is True


def describe(title, plan):
    """Never render arbitrary values from JSON plans (which contain secrets)."""
    changes = [item for item in plan.get("resource_changes", []) if item["change"]["actions"] != ["no-op"]]
    counts = {"Create": 0, "Update": 0, "Delete": 0, "Replace": 0}
    lines = [f"## Terraform plan: {cell(title)}", "", "| Action | Resource |", "| --- | --- |"]
    for item in changes:
        change = item["change"]
        actions = change["actions"]
        action = "replace" if "delete" in actions and "create" in actions else ",".join(actions)
        label = {"create": "Create", "update": "Update", "delete": "Delete", "replace": "Replace"}.get(action)
        if label:
            counts[label] += 1
        lines.append(f"| {action} | `{cell(item['address'])}` |")
    if not changes:
        lines.append("| no-op | No resource changes |")
    lines[2:2] = ["; ".join(f"**{key}: {value}**" for key, value in counts.items()), ""]
    fields = []
    for item in changes:
        change = item["change"]
        before, after = change.get("before") or {}, change.get("after") or {}
        names = sorted(field for field in set(before) | set(after) | set(change.get("after_unknown") or {}) if before.get(field) != after.get(field) or protected((change.get("after_unknown") or {}).get(field)))
        if names:
            lines += ["", f"Changed fields in `{cell(item['address'])}`: " + ", ".join(f"`{cell(name)}`" for name in names)]
        for field in sorted(PUBLIC_FIELDS.get(item.get("type"), set())):
            if before.get(field) == after.get(field):
                continue
            flags = [change.get(key) or {} for key in ("before_sensitive", "after_sensitive", "after_unknown")]
            if any(protected(value.get(field) if isinstance(value, dict) else value) for value in flags):
                continue
            fields.append(f"| `{cell(item['address'])}.{field}` | `{cell(json.dumps(before.get(field)))}` | `{cell(json.dumps(after.get(field)))}` |")
    if fields:
        lines += ["", "Selected non-sensitive changes:", "", "| Field | Before | After |", "| --- | --- | --- |", *fields]
    changed_outputs = [name for name, change in plan.get("output_changes", {}).items() if change.get("actions") != ["no-op"]]
    if changed_outputs:
        lines += ["", "Output changes (values omitted): " + ", ".join(f"`{cell(name)}`" for name in changed_outputs)]
    lines += ["", "Other values, including credentials and generated keys, are omitted from this review."]
    summary("\n".join(lines))


def backend(stack, state_key):
    directory = Path("stacks") / stack
    (directory / "backend.generated.tf").write_text('terraform {\n  backend "s3" {\n    use_lockfile = true\n  }\n}\n')
    run("terraform", f"-chdir={directory}", "init", "-reconfigure", "-input=false",
        f"-backend-config=bucket={os.environ['TF_STATE_BUCKET_NAME']}",
        f"-backend-config=region={os.environ['TF_STATE_REGION_NAME']}", f"-backend-config=key={state_key}")
    # Keep the raw init result with each saved plan, including empty override locks.
    lock = directory / ".terraform.lock.hcl"
    if not lock.exists():
        lock.write_text("")
    return directory


def dependency_lock_content(path, overridden_provider=False):
    content = path.read_text()
    if overridden_provider:
        # This Registry entry does not select the active development binary.
        # Its identity is independently enforced by the reviewed binary SHA-256.
        content = re.sub(r'^provider "registry\.terraform\.io/redislabs/rediscloud" \{\n.*?^\}\n?',
                         "", content, flags=re.MULTILINE | re.DOTALL)
    return "\n".join(line.rstrip() for line in content.splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))


def prepare_apply_backend(bundle, item, overridden_provider):
    directory = Path("stacks") / item["stack"]
    reviewed_lock = bundle / item["lock"]
    lock = directory / ".terraform.lock.hcl"
    shutil.copyfile(reviewed_lock, lock)
    backend(item["stack"], item["state_key"])
    if dependency_lock_content(lock, overridden_provider) != dependency_lock_content(reviewed_lock, overridden_provider):
        raise ValueError("Provider dependencies changed after approval; generate a new plan.")
    # Apply must see exactly the lock snapshot embedded in its saved plan.
    # init can add/remove an ignored Registry entry under dev_overrides.
    shutil.copyfile(reviewed_lock, lock)
    return directory


def entries(manifest, phase):
    result = []
    subscription = manifest["subscription"]
    if subscription["mode"] == "managed":
        result.append(("subscription", subscription))
    result += [("database", item) for item in manifest["databases"] if item["mode"] == "managed"]
    result += [("agent-memory", item) for item in manifest["agent_memory_stores"] if item["mode"] == "managed"]
    if phase == "destroy":
        # Reverse phases, preserve the stable order of siblings.
        return sorted(result, key=lambda entry: {"agent-memory": 0, "database": 1, "subscription": 2}[entry[0]])
    return result if phase in {"preview", "rollout"} else [entry for entry in result if entry[0] == phase]


def plan_phase(args):
    manifest = json.loads(args.manifest.read_text())
    bundle = args.bundle
    bundle.mkdir(parents=True, exist_ok=True)
    review = {"schema": 1, "phase": args.phase, "commit": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "created": int(time.time()), "provider_ref": os.environ["RESOLVED_PROVIDER_REF"],
              "terraform_version": os.environ["TF_VERSION"], "plans": []}
    if args.phase == "rollout":
        summary("## One approval for the full configuration\n\nApprove once to execute subscription, database and Agent Memory in dependency order. Existing resources are planned below. When a dependency must first be created or renamed, its dependent plan is deferred until after approval. These deferred changes are authorized by the configuration inventory below, not by a Terraform plan available now. Failure stops subsequent work; completed changes are not automatically rolled back.")
        config_path = Path(manifest["config_path"])
        if not config_path.is_absolute():
            summary(f"[Review the exact configuration]({os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/blob/{os.environ['GITHUB_SHA']}/{config_path.as_posix()})\n")
        summary("\n| Stack | Configured resource |\n| --- | --- |")
        for stack, item in entries(manifest, args.phase):
            summary(f"| {stack} | {cell(item['name'])} |")
    pending_subscription = False
    pending_databases = set()
    needs_apply = False
    for index, (stack, item) in enumerate(entries(manifest, args.phase)):
        deferred = args.phase in {"preview", "rollout"} and (
            (stack == "database" and pending_subscription) or
            (stack == "agent-memory" and item.get("database_key") in pending_databases))
        if deferred:
            if stack == "database":
                pending_databases.add(item["key"])
            if args.phase == "preview":
                summary(f"## Terraform plan: {cell(stack + ' ' + item['name'])}\n\nSkipped in plan-only mode: dependency creation/replacement/rename is pending.")
                continue
            summary(f"## Deferred plan: {cell(stack + ' ' + item['name'])}\n\nIts dependency is pending. The actual plan will be generated and checked after the single approval, before applying this phase.")
            directory = backend(stack, item["state_key"])
            variables = f"variables-{index}.json"
            lock = f"lock-{index}.hcl"
            shutil.copyfile(item["tfvars_path"], bundle / variables)
            shutil.copyfile(directory / ".terraform.lock.hcl", bundle / lock)
            review["plans"].append({"stack": stack, "title": stack + " " + item["name"],
                "state_key": item["state_key"], "deferred": True,
                "variables": variables, "variables_sha256": digest(bundle / variables),
                "lock": lock, "lock_sha256": digest(bundle / lock)})
            needs_apply = True
            continue
        directory = backend(stack, item["state_key"])
        if args.phase == "destroy":
            # An empty state must not trigger name lookups against deleted parents.
            if not run("terraform", f"-chdir={directory}", "state", "list", capture=True).strip():
                summary(f"## Terraform plan: {cell(stack + ' ' + item['name'])}\n\nNo resources in this state; nothing to destroy.")
                continue
        name = f"review-{index}.tfplan"
        command = ["terraform", f"-chdir={directory}", "plan", "-input=false",
                   f"-var-file={Path(item['tfvars_path']).resolve()}", f"-out={name}"]
        if args.phase == "destroy":
            command.append("-destroy")
        run(*command)
        plan = json.loads(run("terraform", f"-chdir={directory}", "show", "-json", name, capture=True))
        describe(stack + " " + item["name"], plan)
        if args.phase != "destroy" and any(item.get("type") == "rediscloud_agent_memory" and "delete" in item["change"]["actions"] for item in plan.get("resource_changes", [])):
            raise ValueError("Plan would delete or replace an Agent Memory service. Use the Redis Cloud Config Destroy workflow for explicit destructive operations.")
        if args.phase in {"preview", "rollout"}:
            if stack == "subscription":
                pending_subscription = dependency_status(plan, "rediscloud_subscription") == "pending"
            elif stack == "database" and dependency_status(plan, "rediscloud_subscription_database") == "pending":
                pending_databases.add(item["key"])
        changed = any(item["change"]["actions"] != ["no-op"] for item in plan.get("resource_changes", [])) or any(item.get("actions") != ["no-op"] for item in plan.get("output_changes", {}).values())
        needs_apply |= changed
        target = bundle / name
        shutil.copyfile(directory / name, target)
        lock = directory / ".terraform.lock.hcl"
        lock_name = f"lock-{index}.hcl"
        shutil.copyfile(lock, bundle / lock_name)
        review["plans"].append({"stack": stack, "title": stack + " " + item["name"], "state_key": item["state_key"], "file": name, "sha256": digest(target), "lock": lock_name, "lock_sha256": digest(bundle / lock_name)})
    output("needs_apply", str(needs_apply and args.phase != "preview").lower())
    if args.phase == "preview" or not needs_apply:
        summary("\nNo deployment approval is requested." if not needs_apply else "\nPlan-only preview; no changes will be applied.")
        return
    binary = os.environ.get("PROVIDER_BINARY", "")
    if binary:
        shutil.copyfile(binary, bundle / "terraform-provider-rediscloud")
        (bundle / "terraform-provider-rediscloud").chmod(0o700)
        review["provider_sha256"] = digest(bundle / "terraform-provider-rediscloud")
    (bundle / "index.json").write_text(json.dumps(review, indent=2))
    archive = bundle.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as stream:
        for path in sorted(bundle.iterdir()):
            stream.add(path, arcname=path.name)
    namespace = manifest["subscription"]["state_key"].rsplit("/", 1)[0]
    key = f"{namespace}/review-plans/{review['run_id']}/{review['attempt']}/{args.phase}.tar.gz"
    run("aws", "s3api", "put-object", "--bucket", os.environ["TF_STATE_BUCKET_NAME"], "--key", key,
        "--body", str(archive), "--server-side-encryption", "AES256", capture=True)
    output("bundle_key", key)
    output("bundle_sha256", digest(archive))
    execution = "The single approval authorizes the whole configuration. Reviewed plans are reused; only explicitly deferred plans are generated after dependencies become available, with the same provider and frozen inputs." if args.phase == "rollout" else "The apply job downloads the same encrypted bundle and never replans."
    summary(f"\n## Approval required: {args.phase}\n\nReview the plans above before approving the **dev** deployment. {execution} Approval expires one hour after planning.\n\n- Config commit: `{review['commit']}`\n- Provider: `{review['provider_ref']}`\n- Bundle SHA-256: `{digest(archive)}`\n- [Open this run's plan summaries]({os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{review['run_id']})")


def load_bundle(args):
    archive = args.bundle.with_suffix(".tar.gz")
    run("aws", "s3api", "get-object", "--bucket", os.environ["TF_STATE_BUCKET_NAME"], "--key", args.key, str(archive), capture=True)
    if digest(archive) != args.sha256:
        raise ValueError("Reviewed bundle checksum mismatch; generate a new plan.")
    args.bundle.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        if any(not item.isfile() or Path(item.name).name != item.name for item in stream.getmembers()):
            raise ValueError("Invalid review bundle members.")
        stream.extractall(args.bundle, filter="data")
    review = validate_bundle(args.bundle, args.phase)
    binary = args.bundle / "terraform-provider-rediscloud"
    output("provider_binary", str(binary.resolve()) if binary.is_file() else "")
    return review


def validate_bundle(bundle, phase):
    review = json.loads((bundle / "index.json").read_text())
    for key, expected in (("schema", 1), ("phase", phase), ("commit", os.environ["GITHUB_SHA"]),
                          ("run_id", os.environ["GITHUB_RUN_ID"]), ("attempt", os.environ["GITHUB_RUN_ATTEMPT"]),
                          ("terraform_version", os.environ["TF_VERSION"])):
        if review.get(key) != expected:
            raise ValueError(f"Reviewed bundle {key} mismatch.")
    age = time.time() - review["created"]
    if age < -60 or age > 3600:
        raise ValueError("Reviewed plan expired; generate and approve a new plan.")
    for item in review["plans"]:
        if item["stack"] not in STACKS or (phase not in {"destroy", "rollout"} and item["stack"] != phase):
            raise ValueError("Unexpected stack in reviewed plan.")
        payload = ("variables", "variables_sha256") if item.get("deferred") else ("file", "sha256")
        if item.get("deferred") and phase != "rollout":
            raise ValueError("Deferred plans require whole-configuration approval.")
        for path_key, hash_key in (payload, ("lock", "lock_sha256")):
            if Path(item[path_key]).name != item[path_key] or digest(bundle / item[path_key]) != item[hash_key]:
                raise ValueError("Reviewed plan file checksum mismatch.")
    if "provider_sha256" in review and digest(bundle / "terraform-provider-rediscloud") != review["provider_sha256"]:
        raise ValueError("Reviewed provider binary checksum mismatch.")
    return review


def apply_phase(args):
    review = validate_bundle(args.bundle, args.phase)
    if "provider_sha256" in review and digest(Path(os.environ["PROVIDER_BINARY"])) != review["provider_sha256"]:
        raise ValueError("The active provider is not the reviewed provider binary.")
    if args.phase == "rollout":
        apply_rollout(args.bundle, review)
        return
    # Validate every file before any apply in this phase.
    for item in review["plans"]:
        directory = prepare_apply_backend(args.bundle, item, "provider_sha256" in review)
        target = directory / "approved.tfplan"
        shutil.copyfile(args.bundle / item["file"], target)
        print(("Destroying " if args.phase == "destroy" else "Applying ") + item["title"], flush=True)
        run("terraform", f"-chdir={directory}", "apply", "-input=false", "-auto-approve", target.name)
        summary(f"## Approved plan applied: {cell(item['title'])}\n\nSHA-256: `{item['sha256']}`")


def apply_rollout(bundle, review):
    # All reviewed files/provider were checked before the first mutation.
    # Generate every deferred plan in a phase before applying any sibling.
    for stack in ("subscription", "database", "agent-memory"):
        phase = []
        for index, item in enumerate(review["plans"]):
            if item["stack"] != stack:
                continue
            directory = prepare_apply_backend(bundle, item, "provider_sha256" in review)
            if item.get("deferred"):
                name = f"deferred-{index}.tfplan"
                run("terraform", f"-chdir={directory}", "plan", "-input=false",
                    f"-var-file={(bundle / item['variables']).resolve()}", f"-out={name}")
                plan = json.loads(run("terraform", f"-chdir={directory}", "show", "-json", name, capture=True))
                describe("Post-approval deferred plan: " + item["title"], plan)
                if any(change.get("type") == "rediscloud_agent_memory" and "delete" in change["change"]["actions"] for change in plan.get("resource_changes", [])):
                    raise ValueError("Deferred plan would delete or replace an Agent Memory service. Use the Redis Cloud Config Destroy workflow.")
                # A deferred plan also rechecks its dependency/input bindings via Terraform.
                path = bundle / name
                shutil.copyfile(directory / name, path)
            else:
                path = bundle / item["file"]
            phase.append((item, path))
        for item, path in phase:
            directory = prepare_apply_backend(bundle, item, "provider_sha256" in review)
            shutil.copyfile(path, directory / "approved.tfplan")
            print("Applying " + item["title"], flush=True)
            run("terraform", f"-chdir={directory}", "apply", "-input=false", "-auto-approve", "approved.tfplan")
            summary(f"## Approved configuration applied: {cell(item['title'])}\n\nPlan SHA-256: `{digest(path)}`")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "load", "apply"])
    parser.add_argument("--phase", required=True, choices=[*sorted(STACKS), "preview", "destroy", "rollout"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--key")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        {"plan": plan_phase, "load": load_bundle, "apply": apply_phase}[args.command](args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"Reviewed Terraform execution stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
