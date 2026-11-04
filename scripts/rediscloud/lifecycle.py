"""Review and apply exactly one Terraform plan for a subscription JSON."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import bundles, reporting, terraform


def validate_plan(plan, manifest):
    """Check exceptional ownership/binding cases using Terraform's plan interface.

    Ordinary relationships are declared in HCL. These checks cover raw external
    database IDs and prevent an ownership-mode change from silently deleting a
    previously managed resource. No raw state format or S3 state reads are used.
    """
    changes = [
        r
        for r in plan.get("resource_changes", [])
        if r.get("mode", "managed") == "managed"
    ]
    deleted_databases = {
        str((r["change"].get("before") or {}).get("db_id"))
        for r in changes
        if r["type"] == "rediscloud_subscription_database"
        and "delete" in r["change"]["actions"]
    }
    for resource in changes:
        change = resource["change"]
        if (
            resource["type"] == "rediscloud_agent_memory"
            and "delete" not in change["actions"]
        ):
            if str((change.get("after") or {}).get("database_id")) in deleted_databases:
                raise ValueError(
                    "A retained Agent Memory still uses a database scheduled for deletion."
                )
        if "delete" in change["actions"]:
            external = []
            if manifest["subscription"]["mode"] == "external":
                external.append("module.subscription[0].")
            for collection, module in (
                ("databases", "database"),
                ("agent_memory_stores", "agent_memory"),
            ):
                external += [
                    f'module.{module}["{item["key"]}"].'
                    for item in manifest[collection]
                    if item["mode"] == "external"
                ]
            if any(resource["address"].startswith(prefix) for prefix in external):
                raise ValueError(
                    "Changing managed resources to external requires explicit ownership transfer."
                )
    selected = manifest.get("selected_module")
    if selected and any(
        r["change"]["actions"] != ["no-op"]
        and (
            not r["address"].startswith(selected + ".")
            or r["change"]["actions"] != ["delete"]
        )
        for r in changes
    ):
        raise ValueError(
            "Selective destroy may only delete the selected Agent Memory; reconcile other changes first."
        )


def plan_phase(args):
    manifest = json.loads(args.manifest.read_text())
    item = manifest["deployment"]
    args.bundle.mkdir(parents=True, exist_ok=True)
    directory = terraform.backend("deployment", item["state_key"])
    deleting = args.phase == "destroy" and not manifest.get("selected_module")
    plan = terraform.plan(
        directory, Path(item["tfvars_path"]), "review.tfplan", destroy=deleting
    )
    validate_plan(plan, manifest)
    reporting.describe("deployment " + item["name"], plan)
    needs_apply = terraform.has_changes(plan)
    reporting.output(
        "needs_apply", str(needs_apply and args.phase != "preview").lower()
    )
    if not needs_apply or args.phase == "preview":
        reporting.summary(
            "No deployment approval is requested."
            if not needs_apply
            else "Plan-only preview; no changes will be applied."
        )
        return
    review = bundles.new_review(args.phase)
    review["plans"].append(
        bundles.save_plan(
            args.bundle, 0, "deployment", item, directory, "review.tfplan"
        )
    )
    key, checksum = bundles.publish(args.bundle, manifest, review)
    reporting.output("bundle_key", key)
    reporting.output("bundle_sha256", checksum)
    reporting.describe_approval(review, checksum)


def apply_phase(args):
    review = bundles.validate_bundle(args.bundle, args.phase)
    overridden = "provider_sha256" in review
    if (
        overridden
        and bundles.digest(Path(os.environ["PROVIDER_BINARY"]))
        != review["provider_sha256"]
    ):
        raise ValueError("The active provider is not the reviewed provider binary.")
    item = review["plans"][0]
    directory = terraform.prepare_apply_backend(args.bundle, item, overridden)
    shutil.copyfile(args.bundle / item["file"], directory / "approved.tfplan")
    terraform.apply(directory, "approved.tfplan")
    reporting.summary("Approved deployment plan applied. No replanning was performed.")
