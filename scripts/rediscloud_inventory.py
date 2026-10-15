"""Find omitted, previously managed stacks in one subscription state namespace.

State contents stay private. Only minimal non-secret destroy inputs are retained;
Terraform still refreshes and plans each deletion before manual approval.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from rediscloud_config import KEY_PATTERN, NAME_PATTERN


RESOURCES = {
    "agent-memory": {
        ("rediscloud_agent_memory", "this"),
        ("rediscloud_agent_memory_api_key", "this"),
        ("terraform_data", "validation"),
        ("terraform_data", "agent_memory_database_validation"),
    },
    "database": {
        ("rediscloud_subscription_database", "this"),
        ("rediscloud_acl_rule", "this"),
        ("rediscloud_acl_role", "this"),
        ("rediscloud_acl_user", "this"),
        ("random_password", "acl_user"),
        ("terraform_data", "validation"),
    },
}


def attributes(state, stack):
    """Reject unfamiliar states instead of guessing which resources to delete."""
    managed = []
    for resource in state.get("resources", []):
        if resource.get("mode") == "data":
            continue
        if (resource.get("mode") != "managed" or resource.get("module") or
                (resource.get("type"), resource.get("name")) not in RESOURCES[stack]):
            raise ValueError("Unrecognized resources in an omitted state; reconcile ownership manually.")
        for instance in resource.get("instances", []):
            managed.append((resource["type"], instance.get("attributes") or {}))
    return managed


def destroy_variables(state, stack):
    managed = attributes(state, stack)
    if not managed:
        return None
    primary = "rediscloud_agent_memory" if stack == "agent-memory" else "rediscloud_subscription_database"
    records = [values for kind, values in managed if kind == primary]
    if len(records) != 1:
        # A failed create can leave validation resources alone, with no cloud ID.
        if all(kind == "terraform_data" for kind, _ in managed):
            return ({"agent_memory_name": "removed-agent", "database_id": 1} if stack == "agent-memory"
                    else {"database_name": "removed-database", "subscription_id": 1,
                          "acl_user_password_override": "unused-during-destroy"})
        raise ValueError("Omitted state has no unique primary resource; reconcile its partial creation manually.")
    values = records[0]
    name = values.get("name")
    parent = values.get("database_id" if stack == "agent-memory" else "subscription_id")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or not re.fullmatch(r"[1-9][0-9]*", str(parent)):
        raise ValueError("Omitted state lacks valid name/parent identity; reconcile it manually.")
    # Avoid evaluating coalesce(null, null) for databases originally configured
    # with an explicit ACL password (no random_password instance in state).
    # This placeholder is never applied: the runner requires a deletion-only plan.
    return ({"agent_memory_name": name, "database_id": int(parent)} if stack == "agent-memory"
            else {"database_name": name, "subscription_id": int(parent),
                  "acl_user_password_override": "unused-during-destroy"})


def removed_entries(manifest, out_dir, run):
    namespace = f"subscriptions/{manifest['subscription_key']}"
    if (not KEY_PATTERN.fullmatch(manifest["subscription_key"]) or
            manifest["subscription"]["state_key"] != f"{namespace}/subscription.tfstate"):
        raise ValueError("Invalid subscription state namespace.")
    listing = json.loads(run("aws", "s3api", "list-objects-v2", "--bucket", os.environ["TF_STATE_BUCKET_NAME"],
                             "--prefix", namespace + "/", "--output", "json", capture=True))
    wanted = {
        "agent-memory": {item["key"]: item for item in manifest["agent_memory_stores"]},
        "database": {item["key"]: item for item in manifest["databases"]},
    }
    removed = []
    with tempfile.TemporaryDirectory(prefix="rediscloud-inventory-", dir=os.environ.get("RUNNER_TEMP")) as tmp:
        def read_state(key):
            path = Path(tmp) / "state.json"
            run("aws", "s3api", "get-object", "--bucket", os.environ["TF_STATE_BUCKET_NAME"],
                "--key", key, str(path), capture=True)
            state = json.loads(path.read_text())
            if state.get("version") != 4 or not isinstance(state.get("resources"), list):
                raise ValueError("Unsupported state format; reconcile manually.")
            return state

        retained_agents = []
        removed_database_ids = set()
        for key in sorted({item["Key"] for item in listing.get("Contents", [])}):
            # Ignore lock files, review bundles, historical versions and other namespaces.
            match = re.fullmatch(re.escape(namespace) + r"/(agent-memory|databases)/([^/]+)\.tfstate", key)
            if not match:
                continue
            folder, resource_key = match.groups()
            if not KEY_PATTERN.fullmatch(resource_key):
                raise ValueError("Unexpected state key in subscription namespace; reconcile manually.")
            stack = "database" if folder == "databases" else "agent-memory"
            configured = wanted[stack].get(resource_key)
            if configured and configured["mode"] == "managed":
                if stack == "agent-memory":
                    retained_agents.append(key)
                continue
            state = read_state(key)
            variables = destroy_variables(state, stack)
            if variables is None:
                continue
            if configured:
                raise ValueError("A managed state is now marked external; transfer its ownership explicitly before applying.")
            name = variables.get("agent_memory_name", variables.get("database_name"))
            # Changing a stable config key is a state migration, not a deletion.
            if any(item.get("name") == name for item in wanted[stack].values()):
                raise ValueError("An omitted resource reappears under another key; migrate its state instead of renaming the key.")
            if stack == "database":
                ids = [values.get("db_id") or str(values.get("id", "")).rsplit("/", 1)[-1] for kind, values in attributes(state, stack)
                       if kind == "rediscloud_subscription_database"]
                if any(not re.fullmatch(r"[1-9][0-9]*", str(value)) for value in ids):
                    raise ValueError("Omitted database has no valid ID; reconcile it manually.")
                removed_database_ids.update(str(value) for value in ids)
                configured_ids = [item.get("database_id") for item in manifest["databases"]]
                configured_ids += [item.get("database_id") for item in manifest["agent_memory_stores"]]
                if any(value is not None and str(value) in {str(item) for item in ids} for value in configured_ids):
                    raise ValueError("An omitted database is still referenced by ID; remove its dependents or transfer ownership explicitly.")
            variables_path = out_dir / f"removed-{stack}-{resource_key}.json"
            variables_path.write_text(json.dumps(variables))
            removed.append((stack, {"key": resource_key, "name": name, "state_key": key,
                                    "tfvars_path": str(variables_path), "removed": True}))
        # Check current state bindings too, before approving any deletion. A
        # retained agent's new database may be deferred until after approval.
        if removed_database_ids:
            for key in retained_agents:
                if any(kind == "rediscloud_agent_memory" and str(values.get("database_id")) in removed_database_ids
                       for kind, values in attributes(read_state(key), "agent-memory")):
                    raise ValueError("A retained Agent Memory still uses an omitted database; remove that agent entry before deleting the database.")
    return sorted(removed, key=lambda entry: {"agent-memory": 0, "database": 1}[entry[0]])
