"""Reconcile omitted resources against private subscription state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from .config_common import KEY_PATTERN, NAME_PATTERN
from .agent_memory import agent_destroy_variables
from .database import database_destroy_variables
from .stacks import RESOURCES, DESTROY_ORDER


def attributes(state, stack):
    """Reject unfamiliar states instead of guessing which resources to delete."""
    managed = []
    for resource in state.get("resources", []):
        if resource.get("mode") == "data":
            continue
        if (
            resource.get("mode") != "managed"
            or resource.get("module")
            or (resource.get("type"), resource.get("name")) not in RESOURCES[stack]
        ):
            raise ValueError(
                "Unrecognized resources in an omitted state; reconcile ownership manually."
            )
        for instance in resource.get("instances", []):
            managed.append((resource["type"], instance.get("attributes") or {}))
    return managed


def destroy_variables(state, stack):
    managed = attributes(state, stack)
    if not managed:
        return None
    primary = (
        "rediscloud_agent_memory" if stack == "agent-memory" else "rediscloud_subscription_database"
    )
    records = [values for kind, values in managed if kind == primary]
    if len(records) != 1:
        # A failed create can leave validation resources alone, with no cloud ID.
        if all(kind == "terraform_data" for kind, _ in managed):
            return (
                agent_destroy_variables({}, "removed-agent", 1)
                if stack == "agent-memory"
                else database_destroy_variables("removed-database", 1)
            )
        raise ValueError(
            "Omitted state has no unique primary resource; reconcile its partial creation manually."
        )
    values = records[0]
    name = values.get("name")
    parent = values.get("database_id" if stack == "agent-memory" else "subscription_id")
    if (
        not isinstance(name, str)
        or not NAME_PATTERN.fullmatch(name)
        or not re.fullmatch(r"[1-9][0-9]*", str(parent))
    ):
        raise ValueError("Omitted state lacks valid name/parent identity; reconcile it manually.")
    if stack == "agent-memory":
        return agent_destroy_variables(values, name, int(parent))
    return database_destroy_variables(name, int(parent))


def read_state(key: str, directory: Path, run) -> dict:
    path = directory / "state.json"
    run(
        "aws",
        "s3api",
        "get-object",
        "--bucket",
        os.environ["TF_STATE_BUCKET_NAME"],
        "--key",
        key,
        str(path),
        capture=True,
    )
    state = json.loads(path.read_text())
    if state.get("version") != 4 or not isinstance(state.get("resources"), list):
        raise ValueError("Unsupported state format; reconcile manually.")
    return state


def validate_ownership(configured, name: str, desired_entries: dict) -> None:
    if configured:
        raise ValueError(
            "A managed state is now marked external; transfer its ownership explicitly before applying."
        )
    # A stable-key rename requires migration rather than deleting the original.
    if any(item.get("name") == name for item in desired_entries.values()):
        raise ValueError(
            "An omitted resource reappears under another key; migrate its state instead of renaming the key."
        )


def database_ids_to_remove(state: dict, manifest: dict) -> set[str]:
    ids = [
        values.get("db_id") or str(values.get("id", "")).rsplit("/", 1)[-1]
        for kind, values in attributes(state, "database")
        if kind == "rediscloud_subscription_database"
    ]
    if any(not re.fullmatch(r"[1-9][0-9]*", str(value)) for value in ids):
        raise ValueError("Omitted database has no valid ID; reconcile it manually.")
    result = {str(value) for value in ids}
    configured_ids = [item.get("database_id") for item in manifest["databases"]]
    configured_ids += [item.get("database_id") for item in manifest["agent_memory_stores"]]
    if any(value is not None and str(value) in result for value in configured_ids):
        raise ValueError(
            "An omitted database is still referenced by ID; remove its dependents or transfer ownership explicitly."
        )
    return result


def validate_retained_agent_bindings(keys: list, removed_ids: set, directory: Path, run) -> None:
    # Current bindings matter even when a retained agent's new database is deferred.
    for key in keys:
        if any(
            kind == "rediscloud_agent_memory" and str(values.get("database_id")) in removed_ids
            for kind, values in attributes(read_state(key, directory, run), "agent-memory")
        ):
            raise ValueError(
                "A retained Agent Memory still uses an omitted database; remove that agent entry before deleting the database."
            )


def removed_entries(manifest, out_dir, run):
    namespace = f"subscriptions/{manifest['subscription_key']}"
    if (
        not KEY_PATTERN.fullmatch(manifest["subscription_key"])
        or manifest["subscription"]["state_key"] != f"{namespace}/subscription.tfstate"
    ):
        raise ValueError("Invalid subscription state namespace.")
    listing = json.loads(
        run(
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            os.environ["TF_STATE_BUCKET_NAME"],
            "--prefix",
            namespace + "/",
            "--output",
            "json",
            capture=True,
        )
    )
    wanted = {
        "agent-memory": {item["key"]: item for item in manifest["agent_memory_stores"]},
        "database": {item["key"]: item for item in manifest["databases"]},
    }
    removed = []
    with tempfile.TemporaryDirectory(
        prefix="rediscloud-inventory-", dir=os.environ.get("RUNNER_TEMP")
    ) as tmp:
        retained_agents = []
        removed_database_ids = set()
        for key in sorted({item["Key"] for item in listing.get("Contents", [])}):
            # Ignore lock files, review bundles, historical versions and other namespaces.
            match = re.fullmatch(
                re.escape(namespace) + r"/(agent-memory|databases)/([^/]+)\.tfstate", key
            )
            if not match:
                continue
            folder, resource_key = match.groups()
            if not KEY_PATTERN.fullmatch(resource_key):
                raise ValueError(
                    "Unexpected state key in subscription namespace; reconcile manually."
                )
            stack = "database" if folder == "databases" else "agent-memory"
            configured = wanted[stack].get(resource_key)
            if configured and configured["mode"] == "managed":
                if stack == "agent-memory":
                    retained_agents.append(key)
                continue
            state = read_state(key, Path(tmp), run)
            variables = destroy_variables(state, stack)
            if variables is None:
                continue
            name = variables.get("agent_memory_name", variables.get("database_name"))
            validate_ownership(configured, name, wanted[stack])
            if stack == "database":
                removed_database_ids.update(database_ids_to_remove(state, manifest))
            variables_path = out_dir / f"removed-{stack}-{resource_key}.json"
            variables_path.write_text(json.dumps(variables))
            removed.append(
                (
                    stack,
                    {
                        "key": resource_key,
                        "name": name,
                        "state_key": key,
                        "tfvars_path": str(variables_path),
                        "removed": True,
                    },
                )
            )
        if removed_database_ids:
            validate_retained_agent_bindings(retained_agents, removed_database_ids, Path(tmp), run)
    return sorted(removed, key=lambda entry: DESTROY_ORDER.index(entry[0]))
