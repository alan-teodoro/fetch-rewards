"""Coordinate dependency-ordered plans and approved execution."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import bundles, inventory, reporting, stacks, terraform


def deferred_plan(
    bundle: Path, index: int, stack: str, item: dict, *, preview: bool
) -> dict | None:
    title = reporting.cell(stack + " " + item["name"])
    if preview:
        reporting.summary(
            f"## Terraform plan: {title}\n\nSkipped in plan-only mode: dependency creation/replacement/rename is pending."
        )
        return None
    reporting.summary(
        f"## Deferred plan: {title}\n\nIts dependency is pending. The actual plan will be generated and checked after the single approval, before applying this phase."
    )
    directory = terraform.backend(stack, item["state_key"])
    return bundles.freeze_inputs(bundle, index, stack, item, directory)


def reviewed_plan(bundle: Path, index: int, stack: str, item: dict, *, deleting: bool) -> tuple:
    directory = terraform.backend(stack, item["state_key"])
    if (
        deleting
        and not terraform.run(
            "terraform", f"-chdir={directory}", "state", "list", capture=True
        ).strip()
    ):
        # Empty states must not trigger name lookups against deleted parents.
        reporting.summary(
            f"## Terraform plan: {reporting.cell(stack + ' ' + item['name'])}\n\nNo resources in this state; nothing to destroy."
        )
        return None, None
    filename = f"review-{index}.tfplan"
    plan = terraform.plan(directory, Path(item["tfvars_path"]), filename, destroy=deleting)
    reporting.describe(stack + " " + item["name"], plan)
    if item.get("removed") and any(
        change["change"]["actions"] not in (["delete"], ["no-op"], ["read"])
        for change in plan.get("resource_changes", [])
    ):
        raise ValueError(
            "An omitted resource must have a deletion-only plan; generate a new review."
        )
    return bundles.save_plan(bundle, index, stack, item, directory, filename), plan


def plan_phase(args):
    manifest = json.loads(args.manifest.read_text())
    bundle = args.bundle
    bundle.mkdir(parents=True, exist_ok=True)
    review = bundles.new_review(args.phase)
    omitted = []
    if args.phase in {"preview", "rollout"} or (
        args.phase == "destroy" and manifest.get("destroy_scope") == "all_managed_resources"
    ):
        omitted = inventory.removed_entries(manifest, args.manifest.parent, terraform.run)
    planned_entries = omitted + stacks.entries(manifest, args.phase)
    if args.phase == "destroy":
        planned_entries.sort(key=lambda entry: stacks.DESTROY_ORDER.index(entry[0]))
    reporting.describe_inventory(manifest, args.phase, omitted)

    pending_subscription = False
    pending_databases = set()
    needs_apply = False
    for index, (stack, item) in enumerate(planned_entries):
        deleting = args.phase == "destroy" or item.get("removed", False)
        deferred = (
            not deleting
            and args.phase in {"preview", "rollout"}
            and (
                (stack == "database" and pending_subscription)
                or (stack == "agent-memory" and item.get("database_key") in pending_databases)
            )
        )
        if deferred:
            if stack == "database":
                pending_databases.add(item["key"])
            record = deferred_plan(bundle, index, stack, item, preview=args.phase == "preview")
            if record is not None:
                review["plans"].append(record)
                needs_apply = True
            continue
        record, plan = reviewed_plan(bundle, index, stack, item, deleting=deleting)
        if record is None:
            continue
        if not deleting and args.phase in {"preview", "rollout"}:
            if stack == "subscription":
                pending_subscription = (
                    terraform.dependency_status(plan, "rediscloud_subscription") == "pending"
                )
            elif (
                stack == "database"
                and terraform.dependency_status(plan, "rediscloud_subscription_database")
                == "pending"
            ):
                pending_databases.add(item["key"])
        needs_apply |= terraform.has_changes(plan)
        review["plans"].append(record)

    reporting.output("needs_apply", str(needs_apply and args.phase != "preview").lower())
    if args.phase == "preview" or not needs_apply:
        reporting.summary(
            "\nNo deployment approval is requested."
            if not needs_apply
            else "\nPlan-only preview; no changes will be applied."
        )
        return
    key, checksum = bundles.publish(bundle, manifest, review)
    reporting.output("bundle_key", key)
    reporting.output("bundle_sha256", checksum)
    reporting.describe_approval(review, checksum)


def apply_plan(
    bundle: Path, item: dict, plan_file: Path, overridden_provider: bool, message: str
) -> None:
    directory = terraform.prepare_apply_backend(bundle, item, overridden_provider)
    shutil.copyfile(plan_file, directory / "approved.tfplan")
    print(message + item["title"], flush=True)
    terraform.apply(directory, "approved.tfplan")


def apply_phase(args):
    review = bundles.validate_bundle(args.bundle, args.phase)
    overridden = "provider_sha256" in review
    if (
        overridden
        and bundles.digest(Path(os.environ["PROVIDER_BINARY"])) != review["provider_sha256"]
    ):
        raise ValueError("The active provider is not the reviewed provider binary.")
    if args.phase == "rollout":
        apply_rollout(args.bundle, review)
        return
    # validate_bundle checks every reviewed file before the first apply.
    for item in review["plans"]:
        message = "Destroying " if args.phase == "destroy" else "Applying "
        apply_plan(args.bundle, item, args.bundle / item["file"], overridden, message)
        reporting.summary(
            f"## Approved plan applied: {reporting.cell(item['title'])}\n\nSHA-256: `{item['sha256']}`"
        )


def prepare_phase_plans(bundle: Path, review: dict, stack: str) -> list:
    phase = []
    for index, item in enumerate(review["plans"]):
        if item["stack"] != stack or item.get("removed"):
            continue
        directory = terraform.prepare_apply_backend(bundle, item, "provider_sha256" in review)
        if item.get("deferred"):
            name = f"deferred-{index}.tfplan"
            plan = terraform.plan(directory, bundle / item["variables"], name)
            reporting.describe("Post-approval deferred plan: " + item["title"], plan)
            plan_file = bundle / name
            shutil.copyfile(directory / name, plan_file)
        else:
            plan_file = bundle / item["file"]
        phase.append((item, plan_file))
    return phase


def apply_rollout(bundle: Path, review: dict) -> None:
    overridden = "provider_sha256" in review
    for stack in stacks.DESTROY_ORDER:
        for item in review["plans"]:
            if item["stack"] != stack or not item.get("removed"):
                continue
            apply_plan(bundle, item, bundle / item["file"], overridden, "Removing omitted ")
            reporting.summary(
                f"## Approved deletion applied: {reporting.cell(item['title'])}\n\nPlan SHA-256: `{item['sha256']}`"
            )
    for stack in stacks.CREATE_ORDER:
        # Prepare all deferred siblings before applying any resource in this phase.
        for item, plan_file in prepare_phase_plans(bundle, review, stack):
            apply_plan(bundle, item, plan_file, overridden, "Applying ")
            reporting.summary(
                f"## Approved configuration applied: {reporting.cell(item['title'])}\n\nPlan SHA-256: `{bundles.digest(plan_file)}`"
            )
