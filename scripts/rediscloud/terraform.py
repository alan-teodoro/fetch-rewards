"""Terraform CLI calls, backend initialization and dependency availability."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def run(*args: str, capture=False):
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE if capture else None
    ).stdout


DEPLOYMENT_DIRECTORY = Path("stacks/deployment")


def backend(state_key):
    directory = DEPLOYMENT_DIRECTORY
    run(
        "terraform",
        f"-chdir={directory}",
        "init",
        "-reconfigure",
        "-input=false",
        "-lockfile=readonly",
        f"-backend-config=bucket={os.environ['TF_STATE_BUCKET_NAME']}",
        f"-backend-config=region={os.environ['TF_STATE_REGION_NAME']}",
        f"-backend-config=key={state_key}",
    )
    return directory


def dependency_lock_content(path):
    content = path.read_text()
    return "\n".join(
        line.rstrip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def prepare_apply_backend(bundle, item):
    """Select the reviewed state and reject dependency changes introduced by init."""
    directory = DEPLOYMENT_DIRECTORY
    reviewed_lock = bundle / item["lock"]
    lock = directory / ".terraform.lock.hcl"
    shutil.copyfile(reviewed_lock, lock)
    backend(item["state_key"])
    if dependency_lock_content(lock) != dependency_lock_content(reviewed_lock):
        raise ValueError(
            "Provider dependencies changed after approval; generate a new plan."
        )
    # Apply must see exactly the lock snapshot embedded in its saved plan.
    shutil.copyfile(reviewed_lock, lock)
    return directory


def plan(
    directory: Path, variables: Path, filename: str, *, destroy: bool = False
) -> dict:
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
        item["change"]["actions"] != ["no-op"]
        for item in plan.get("resource_changes", [])
    )
    outputs_changed = any(
        item.get("actions") != ["no-op"]
        for item in plan.get("output_changes", {}).values()
    )
    return resources_changed or outputs_changed


def apply(directory: Path, filename: str) -> None:
    run(
        "terraform",
        f"-chdir={directory}",
        "apply",
        "-input=false",
        "-auto-approve",
        filename,
    )
