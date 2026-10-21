"""Checksums, encrypted review-bundle loading and approval bindings."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import time

from .terraform import run
from .reporting import output
from .stacks import STACKS


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle(args):
    archive = args.bundle.with_suffix(".tar.gz")
    run(
        "aws",
        "s3api",
        "get-object",
        "--bucket",
        os.environ["TF_STATE_BUCKET_NAME"],
        "--key",
        args.key,
        str(archive),
        capture=True,
    )
    if digest(archive) != args.sha256:
        raise ValueError("Reviewed bundle checksum mismatch; generate a new plan.")
    args.bundle.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        if any(
            not item.isfile() or Path(item.name).name != item.name for item in stream.getmembers()
        ):
            raise ValueError("Invalid review bundle members.")
        stream.extractall(args.bundle, filter="data")
    review = validate_bundle(args.bundle, args.phase)
    binary = args.bundle / "terraform-provider-rediscloud"
    output("provider_binary", str(binary.resolve()) if binary.is_file() else "")
    return review


def validate_bundle(bundle, phase):
    review = json.loads((bundle / "index.json").read_text())
    for key, expected in (
        ("schema", 1),
        ("phase", phase),
        ("commit", os.environ["GITHUB_SHA"]),
        ("run_id", os.environ["GITHUB_RUN_ID"]),
        ("attempt", os.environ["GITHUB_RUN_ATTEMPT"]),
        ("terraform_version", os.environ["TF_VERSION"]),
    ):
        if review.get(key) != expected:
            raise ValueError(f"Reviewed bundle {key} mismatch.")
    age = time.time() - review["created"]
    if age < -60 or age > 3600:
        raise ValueError("Reviewed plan expired; generate and approve a new plan.")
    for item in review["plans"]:
        if item["stack"] not in STACKS or (
            phase not in {"destroy", "rollout"} and item["stack"] != phase
        ):
            raise ValueError("Unexpected stack in reviewed plan.")
        payload = ("variables", "variables_sha256") if item.get("deferred") else ("file", "sha256")
        if item.get("deferred") and phase != "rollout":
            raise ValueError("Deferred plans require whole-configuration approval.")
        if item.get("removed") and (
            item["stack"] not in {"agent-memory", "database"} or item.get("deferred")
        ):
            raise ValueError(
                "Omitted resources require reviewed Agent Memory/database deletion plans."
            )
        for path_key, hash_key in (payload, ("lock", "lock_sha256")):
            if (
                Path(item[path_key]).name != item[path_key]
                or digest(bundle / item[path_key]) != item[hash_key]
            ):
                raise ValueError("Reviewed plan file checksum mismatch.")
    if (
        "provider_sha256" in review
        and digest(bundle / "terraform-provider-rediscloud") != review["provider_sha256"]
    ):
        raise ValueError("Reviewed provider binary checksum mismatch.")
    return review


def new_review(phase: str) -> dict:
    return {
        "schema": 1,
        "phase": phase,
        "commit": os.environ["GITHUB_SHA"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "created": int(time.time()),
        "provider_ref": os.environ["RESOLVED_PROVIDER_REF"],
        "terraform_version": os.environ["TF_VERSION"],
        "plans": [],
    }


def save_plan(
    bundle: Path, index: int, stack: str, item: dict, directory: Path, filename: str
) -> dict:
    target = bundle / filename
    shutil.copyfile(directory / filename, target)
    lock_name = f"lock-{index}.hcl"
    shutil.copyfile(directory / ".terraform.lock.hcl", bundle / lock_name)
    return {
        "stack": stack,
        "title": stack + " " + item["name"],
        "state_key": item["state_key"],
        "file": filename,
        "sha256": digest(target),
        "lock": lock_name,
        "lock_sha256": digest(bundle / lock_name),
        "removed": item.get("removed", False),
    }


def freeze_inputs(bundle: Path, index: int, stack: str, item: dict, directory: Path) -> dict:
    variables = f"variables-{index}.json"
    lock = f"lock-{index}.hcl"
    shutil.copyfile(item["tfvars_path"], bundle / variables)
    shutil.copyfile(directory / ".terraform.lock.hcl", bundle / lock)
    return {
        "stack": stack,
        "title": stack + " " + item["name"],
        "state_key": item["state_key"],
        "deferred": True,
        "variables": variables,
        "variables_sha256": digest(bundle / variables),
        "lock": lock,
        "lock_sha256": digest(bundle / lock),
    }


def publish(bundle: Path, manifest: dict, review: dict) -> tuple[str, str]:
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
    key = (
        f"{namespace}/review-plans/{review['run_id']}/{review['attempt']}/{review['phase']}.tar.gz"
    )
    run(
        "aws",
        "s3api",
        "put-object",
        "--bucket",
        os.environ["TF_STATE_BUCKET_NAME"],
        "--key",
        key,
        "--body",
        str(archive),
        "--server-side-encryption",
        "AES256",
        capture=True,
    )
    return key, digest(archive)
