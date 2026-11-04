"""Checksums, encrypted review-bundle loading and approval bindings."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import time
from pathlib import Path

from .terraform import run


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
            not item.isfile() or Path(item.name).name != item.name
            for item in stream.getmembers()
        ):
            raise ValueError("Invalid review bundle members.")
        stream.extractall(args.bundle, filter="data")
    return validate_bundle(args.bundle, args.phase)


def validate_bundle(bundle, phase):
    """Reject stale, mismatched or modified approval payloads before any apply."""
    review = json.loads((bundle / "index.json").read_text())
    for key, expected in (
        ("schema", 2),
        ("phase", phase),
        ("commit", os.environ["GITHUB_SHA"]),
        ("run_id", os.environ["GITHUB_RUN_ID"]),
        ("attempt", os.environ["GITHUB_RUN_ATTEMPT"]),
        ("terraform_version", os.environ["TF_VERSION"]),
        ("deployment_environment", os.environ.get("REDISCLOUD_ENVIRONMENT", "dev")),
        ("state_bucket", os.environ["TF_STATE_BUCKET_NAME"]),
        ("state_region", os.environ["TF_STATE_REGION_NAME"]),
    ):
        if review.get(key) != expected:
            raise ValueError(f"Reviewed bundle {key} mismatch.")
    age = time.time() - review["created"]
    if age < -60 or age > 3600:
        raise ValueError("Reviewed plan expired; generate and approve a new plan.")
    item = review["plan"]
    if item["state_key"] != review["state_key"]:
        raise ValueError("Reviewed state key mismatch.")
    for path_key, hash_key in (("file", "sha256"), ("lock", "lock_sha256")):
        if (
            Path(item[path_key]).name != item[path_key]
            or digest(bundle / item[path_key]) != item[hash_key]
        ):
            raise ValueError("Reviewed plan file checksum mismatch.")
    return review


def new_review(phase: str, state_key: str) -> dict:
    return {
        "schema": 2,
        "phase": phase,
        "commit": os.environ["GITHUB_SHA"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "created": int(time.time()),
        "terraform_version": os.environ["TF_VERSION"],
        "deployment_environment": os.environ.get("REDISCLOUD_ENVIRONMENT", "dev"),
        "state_bucket": os.environ["TF_STATE_BUCKET_NAME"],
        "state_region": os.environ["TF_STATE_REGION_NAME"],
        "state_key": state_key,
    }


def save_plan(bundle: Path, item: dict, directory: Path) -> dict:
    filename = "review.tfplan"
    target = bundle / filename
    shutil.copyfile(directory / filename, target)
    lock_name = "provider.lock.hcl"
    shutil.copyfile(directory / ".terraform.lock.hcl", bundle / lock_name)
    return {
        "state_key": item["state_key"],
        "file": filename,
        "sha256": digest(target),
        "lock": lock_name,
        "lock_sha256": digest(bundle / lock_name),
    }


def publish(bundle: Path, review: dict) -> tuple[str, str]:
    (bundle / "index.json").write_text(json.dumps(review, indent=2))
    archive = bundle.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as stream:
        for path in sorted(bundle.iterdir()):
            stream.add(path, arcname=path.name)
    namespace = review["state_key"].rsplit("/", 1)[0]
    key = f"{namespace}/review-plans/{review['run_id']}/{review['attempt']}/{review['phase']}.tar.gz"
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
