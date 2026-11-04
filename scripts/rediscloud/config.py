"""Load one subscription configuration and coordinate resource rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_memory import (
    render_agent_memory,
    validate_agent_memory_databases,
    validate_agent_memory_stores,
)
from .config_common import (
    SCHEMA_VERSION,
    ConfigError,
    fail_unknown_fields,
    get_mode,
    optional_object,
    read_json,
    require_object,
    require_string,
    validate_key,
    walk_sensitive_literals,
    write_json,
)
from .database import render_database, validate_databases
from .schema import validate_schema
from .subscription import render_subscription, validate_subscription


def load_and_validate(path: Path) -> dict[str, Any]:
    config = read_json(path)
    walk_sensitive_literals("$", config)
    validate_schema(config)
    allowed_root = {
        "$schema",
        "schema_version",
        "customer",
        "environment",
        "subscription_key",
        "subscription",
        "databases",
        "agent_memory_stores",
    }
    fail_unknown_fields("$", config, allowed_root)

    if config.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION}.")

    require_string("$.customer", config.get("customer"))
    require_string("$.environment", config.get("environment"))

    subscription_key = require_string(
        "$.subscription_key", config.get("subscription_key")
    )
    validate_key("$.subscription_key", subscription_key)

    subscription = require_object("$.subscription", config.get("subscription"))
    subscription_mode, subscription_name, subscription_id = validate_subscription(
        subscription
    )
    databases = optional_object("$.databases", config.get("databases"))
    validate_databases(databases)
    stores = optional_object("$.agent_memory_stores", config.get("agent_memory_stores"))
    referenced_databases = validate_agent_memory_stores(stores, databases)
    validate_agent_memory_databases(
        subscription, subscription_mode, databases, referenced_databases
    )

    config["databases"] = databases
    config["agent_memory_stores"] = stores

    config["_normalized"] = {
        "subscription_name": subscription_name,
        "subscription_id": subscription_id,
        "subscription_mode": subscription_mode,
        "referenced_databases": sorted(referenced_databases),
    }
    return config


def build_manifest(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    return {
        "schema_version": config["schema_version"],
        "customer": config["customer"],
        "environment": config["environment"],
        "subscription_key": config["subscription_key"],
        "config_path": str(config_path),
        "subscription": {
            "mode": config["_normalized"]["subscription_mode"],
            "name": config["_normalized"]["subscription_name"],
        },
        "databases": [],
        "agent_memory_stores": [],
    }


def select_destroy_config(
    config: dict[str, Any], agent_memory_key: str | None
) -> dict[str, Any]:
    if not agent_memory_key:
        return config
    stores = config.get("agent_memory_stores", {})
    if agent_memory_key not in stores:
        raise ConfigError(
            f"Unknown Agent Memory key {agent_memory_key!r} for selective destroy."
        )
    store = stores[agent_memory_key]
    if get_mode(f"$.agent_memory_stores.{agent_memory_key}", store) != "managed":
        raise ConfigError(
            f"Agent Memory {agent_memory_key!r} is external and cannot be destroyed by this config."
        )
    return config


def render(
    config_path: Path,
    out_dir: Path,
    *,
    destroy: bool = False,
    agent_memory_key: str | None = None,
) -> dict[str, Any]:
    config = load_and_validate(config_path)
    if agent_memory_key and not destroy:
        raise ConfigError(
            "Selecting an Agent Memory key is only supported for destroy rendering."
        )
    if destroy:
        config = select_destroy_config(config, agent_memory_key)
        config["_destroy"] = not bool(agent_memory_key)
        config["_selected_destroy"] = agent_memory_key
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(config, config_path)
    if destroy:
        manifest["destroy_scope"] = (
            "agent_memory" if agent_memory_key else "all_managed_resources"
        )

    render_subscription(config, manifest)

    for database_key, database in config.get("databases", {}).items():
        render_database(config, database_key, database, manifest)

    for store_key, store in config.get("agent_memory_stores", {}).items():
        render_agent_memory(config, store_key, store, manifest)

    # The JSON describes one root module. Terraform handles references, removals
    # and ordering in a single graph; the renderer never inspects state.
    subscription = {
        **manifest["subscription"].pop("inputs", {}),
        "mode": config["_normalized"]["subscription_mode"],
        "subscription_name": config["_normalized"]["subscription_name"],
        "subscription_id": config["_normalized"]["subscription_id"],
    }
    inputs = {
        "subscription": subscription,
        "databases": {},
        "agent_memory_stores": {},
        "model_api_keys": {},
    }
    for item in manifest["databases"]:
        values = item.pop("inputs", {})
        values.pop("subscription_name", None)
        values.pop("subscription_id", None)
        inputs["databases"][item["key"]] = {
            **values,
            "mode": item["mode"],
            "database_name": item["name"],
            "database_id": item["database_id"],
        }
    for item in manifest["agent_memory_stores"]:
        values = item.pop("inputs", {})
        for name in ("subscription_name", "subscription_id", "database_name"):
            values.pop(name, None)
        credentials = {
            name: values.pop(name)
            for name in ("llm_api_key", "embedding_api_key")
            if name in values
        }
        if destroy and agent_memory_key == item["key"]:
            continue
        if credentials:
            inputs["model_api_keys"][item["key"]] = credentials
        inputs["agent_memory_stores"][item["key"]] = {
            **values,
            "mode": item["mode"],
            "agent_memory_name": item["name"],
            "database_key": item["database_key"],
        }
    tfvars_path = out_dir / "deployment.auto.tfvars.json"
    write_json(tfvars_path, inputs)
    manifest["deployment"] = {
        "name": config["_normalized"]["subscription_name"],
        "state_key": f"subscriptions/{config['subscription_key']}/terraform.tfstate",
        "tfvars_path": str(tfvars_path),
    }
    if destroy and agent_memory_key:
        manifest["selected_module"] = f'module.agent_memory["{agent_memory_key}"]'

    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, manifest)
    return manifest


def validate_workflow_path(path: Path) -> None:
    parts = path.parts
    customer_config = (
        len(parts) == 4 and parts[0] == "configs" and parts[2] == "subscriptions"
    )
    if (
        not customer_config
        or path.suffix != ".json"
        or ".." in parts
        or not path.resolve().is_relative_to(Path.cwd().resolve())
    ):
        raise ConfigError("Use configs/<customer>/subscriptions/<file>.json.")
