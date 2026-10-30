"""Non-secret plan summaries and GitHub Actions outputs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .stacks import PUBLIC_FIELDS, entries


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
    changes = [
        item for item in plan.get("resource_changes", []) if item["change"]["actions"] != ["no-op"]
    ]
    counts = {"Create": 0, "Update": 0, "Delete": 0, "Replace": 0}
    lines = [f"## Terraform plan: {cell(title)}", "", "| Action | Resource |", "| --- | --- |"]
    for item in changes:
        change = item["change"]
        actions = change["actions"]
        action = "replace" if "delete" in actions and "create" in actions else ",".join(actions)
        label = {
            "create": "Create",
            "update": "Update",
            "delete": "Delete",
            "replace": "Replace",
        }.get(action)
        if label:
            counts[label] += 1
        lines.append(f"| {action} | `{cell(item['address'])}` |")
    if not changes:
        lines.append("| no-op | No resource changes |")
    lines[2:2] = ["; ".join(f"**{key}: {value}**" for key, value in counts.items()), ""]
    if any(
        item.get("type") == "rediscloud_agent_memory" and "delete" in item["change"]["actions"]
        for item in changes
    ):
        lines += [
            "",
            "**Agent Memory deletion/replacement:** replacement generates a new store ID and keys. Context is not migrated automatically. Review application references and data retention before applying.",
        ]
    fields = []
    for item in changes:
        change = item["change"]
        before, after = change.get("before") or {}, change.get("after") or {}
        names = sorted(
            field
            for field in set(before) | set(after) | set(change.get("after_unknown") or {})
            if before.get(field) != after.get(field)
            or protected((change.get("after_unknown") or {}).get(field))
        )
        if names:
            lines += [
                "",
                f"Changed fields in `{cell(item['address'])}`: "
                + ", ".join(f"`{cell(name)}`" for name in names),
            ]
        for field in sorted(PUBLIC_FIELDS.get(item.get("type"), set())):
            if before.get(field) == after.get(field):
                continue
            flags = [
                change.get(key) or {}
                for key in ("before_sensitive", "after_sensitive", "after_unknown")
            ]
            if any(
                protected(value.get(field) if isinstance(value, dict) else value) for value in flags
            ):
                continue
            fields.append(
                f"| `{cell(item['address'])}.{field}` | `{cell(json.dumps(before.get(field)))}` | `{cell(json.dumps(after.get(field)))}` |"
            )
    if fields:
        lines += [
            "",
            "Selected non-sensitive changes:",
            "",
            "| Field | Before | After |",
            "| --- | --- | --- |",
            *fields,
        ]
    changed_outputs = [
        name
        for name, change in plan.get("output_changes", {}).items()
        if change.get("actions") != ["no-op"]
    ]
    if changed_outputs:
        lines += [
            "",
            "Output changes (values omitted): "
            + ", ".join(f"`{cell(name)}`" for name in changed_outputs),
        ]
    lines += [
        "",
        "Other values, including credentials and generated keys, are omitted from this review.",
    ]
    summary("\n".join(lines))


def describe_inventory(manifest: dict, phase: str, omitted: list) -> None:
    if omitted:
        summary(
            "## Resources removed from configuration\n\nThe following previously managed states are omitted from this subscription configuration. Their deletion plans are reviewed below and require the same manual approval. Agent Memory is removed before databases; these saved deletion plans execute before creates/updates.\n\n| Stack | Removed resource |\n| --- | --- |"
        )
        for stack, item in omitted:
            summary(f"| {stack} | {cell(item['name'])} |")
    if phase == "rollout":
        summary(
            "## One approval for the full configuration\n\nApprove once to execute subscription, database and Agent Memory in dependency order. Existing resources are planned below. When a dependency must first be created or renamed, its dependent plan is deferred until after approval. These deferred changes are authorized by the configuration inventory below, not by a Terraform plan available now. Failure stops subsequent work; completed changes are not automatically rolled back."
        )
        config_path = Path(manifest["config_path"])
        if not config_path.is_absolute():
            summary(
                f"[Review the exact configuration]({os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/blob/{os.environ['GITHUB_SHA']}/{config_path.as_posix()})\n"
            )
        summary("\n| Stack | Configured resource |\n| --- | --- |")
        for stack, item in entries(manifest, phase):
            summary(f"| {stack} | {cell(item['name'])} |")


def describe_approval(review: dict, bundle_hash: str) -> None:
    environment = cell(os.environ.get("REDISCLOUD_ENVIRONMENT", "dev"))
    execution = (
        "The single approval authorizes the whole configuration. Reviewed plans are reused; only explicitly deferred plans are generated after dependencies become available, with the same provider and frozen inputs."
        if review["phase"] == "rollout"
        else "The apply job downloads the same encrypted bundle and never replans."
    )
    summary(
        f"\n## Approval required: {review['phase']}\n\nReview the plans above before approving the **{environment}** deployment. {execution} Approval expires one hour after planning.\n\n- Config commit: `{review['commit']}`\n- Provider: `{review['provider_ref']}`\n- Bundle SHA-256: `{bundle_hash}`\n- [Open this run's plan summaries]({os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{review['run_id']})"
    )
