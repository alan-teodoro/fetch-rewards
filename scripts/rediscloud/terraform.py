"""Terraform CLI calls, backend initialization and dependency availability."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def run(*args: str, capture=False):
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE if capture else None
    ).stdout


def backend(stack, state_key):
    directory = Path("stacks") / stack
    (directory / "backend.generated.tf").write_text(
        'terraform {\n  backend "s3" {\n    use_lockfile = true\n  }\n}\n'
    )
    run(
        "terraform",
        f"-chdir={directory}",
        "init",
        "-reconfigure",
        "-input=false",
        f"-backend-config=bucket={os.environ['TF_STATE_BUCKET_NAME']}",
        f"-backend-config=region={os.environ['TF_STATE_REGION_NAME']}",
        f"-backend-config=key={state_key}",
    )
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
        content = re.sub(
            r'^provider "registry\.terraform\.io/redislabs/rediscloud" \{\n.*?^\}\n?',
            "",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
    return "\n".join(
        line.rstrip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def prepare_apply_backend(bundle, item, overridden_provider):
    directory = Path("stacks") / item["stack"]
    reviewed_lock = bundle / item["lock"]
    lock = directory / ".terraform.lock.hcl"
    shutil.copyfile(reviewed_lock, lock)
    backend(item["stack"], item["state_key"])
    if dependency_lock_content(lock, overridden_provider) != dependency_lock_content(
        reviewed_lock, overridden_provider
    ):
        raise ValueError("Provider dependencies changed after approval; generate a new plan.")
    # Apply must see exactly the lock snapshot embedded in its saved plan.
    # init can add/remove an ignored Registry entry under dev_overrides.
    shutil.copyfile(reviewed_lock, lock)
    return directory


def dependency_status(plan: dict, resource_type: str) -> str:
    resources = [
        item
        for item in plan.get("resource_changes", [])
        if item.get("mode", "managed") == "managed" and item.get("type") == resource_type
    ]
    if len(resources) != 1:
        raise ValueError(f"Expected exactly one managed {resource_type} resource in the plan.")
    change = resources[0]["change"]
    if any(action in {"create", "delete"} for action in change["actions"]):
        return "pending"
    before = change.get("before") or {}
    after = change.get("after") or {}
    if (change.get("after_unknown") or {}).get("name") or before.get("name") != after.get("name"):
        return "pending"
    return "ready"


def plan(directory: Path, variables: Path, filename: str, *, destroy: bool = False) -> dict:
    command = [
        "terraform",
        f"-chdir={directory}",
        "plan",
        "-input=false",
        f"-var-file={variables.resolve()}",
        f"-out={filename}",
    ]
    if destroy:
        command.append("-destroy")
    run(*command)
    return json.loads(
        run("terraform", f"-chdir={directory}", "show", "-json", filename, capture=True)
    )


def has_changes(plan: dict) -> bool:
    resources_changed = any(
        item["change"]["actions"] != ["no-op"] for item in plan.get("resource_changes", [])
    )
    outputs_changed = any(
        item.get("actions") != ["no-op"] for item in plan.get("output_changes", {}).values()
    )
    return resources_changed or outputs_changed


def apply(directory: Path, filename: str) -> None:
    run("terraform", f"-chdir={directory}", "apply", "-input=false", "-auto-approve", filename)
