"""Non-secret plan summaries and GitHub Actions outputs."""

from __future__ import annotations

import json
import os

PUBLIC_FIELDS = {
    "rediscloud_subscription": {"name", "public_endpoint_access", "memory_storage"},
    "rediscloud_subscription_database": {
        "name",
        "dataset_size_in_gb",
        "throughput_measurement_value",
        "alerts",
        "enable_tls",
        "enable_default_user",
    },
    "rediscloud_agent_memory": {
        "name",
        "database_id",
        "short_term_ttl_seconds",
        "long_term_ttl_seconds",
        "extraction_cadence_seconds",
        "extraction_strategy",
    },
}


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
        item
        for item in plan.get("resource_changes", [])
        if item["change"]["actions"] != ["no-op"]
    ]
    counts = {"Create": 0, "Update": 0, "Delete": 0, "Replace": 0}
    lines = [
        f"## Terraform plan: {cell(title)}",
        "",
        "| Action | Resource |",
        "| --- | --- |",
    ]
    for item in changes:
        change = item["change"]
        actions = change["actions"]
        action = (
            "replace"
            if "delete" in actions and "create" in actions
            else ",".join(actions)
        )
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
        item.get("type") == "rediscloud_agent_memory"
        and "delete" in item["change"]["actions"]
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
            for field in set(before)
            | set(after)
            | set(change.get("after_unknown") or {})
            if before.get(field) != after.get(field)
            or protected((change.get("after_unknown") or {}).get(field))
        )
        actions = change["actions"]
        if names and ("update" in actions or {"create", "delete"} <= set(actions)):
            lines += [
                "",
                f"Changed fields in `{cell(item['address'])}`: "
                + ", ".join(f"`{cell(name)}`" for name in names),
            ]
        if actions in (["delete"], ["read"]):
            continue
        for field in sorted(PUBLIC_FIELDS.get(item.get("type"), set())):
            if before.get(field) == after.get(field):
                continue
            flags = [
                change.get(key) or {}
                for key in ("before_sensitive", "after_sensitive", "after_unknown")
            ]
            if any(
                protected(value.get(field) if isinstance(value, dict) else value)
                for value in flags
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


def describe_approval(review: dict, bundle_hash: str) -> None:
    environment = cell(os.environ.get("REDISCLOUD_ENVIRONMENT", "dev"))
    summary(
        f"## Approval required: {review['phase']}\n\nReview the complete saved Terraform plan before approving **{environment}**. "
        "The apply job reuses this exact plan; no deferred plans or replanning. Approval expires after one hour.\n\n"
        f"- Commit: `{review['commit']}`\n- Provider: Registry version pinned by `.terraform.lock.hcl`\n- Bundle SHA-256: `{bundle_hash}`"
    )
