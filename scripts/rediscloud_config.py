#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MODE_VALUES = {"managed", "external"}
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SUBSCRIPTION_FIELDS = {
    "cloud_provider",
    "region",
    "networking_deployment_cidr",
    "multiple_availability_zones",
    "preferred_availability_zones",
    "public_endpoint_access",
    "memory_storage",
    "payment_method",
    "payment_method_id",
    "payment_card_type",
    "payment_card_last_four",
    "maintenance_windows",
    "tags",
    "enable_resource_tags",
}

SUBSCRIPTION_CREATION_PLAN_FIELDS = {
    "dataset_size_in_gb",
    "throughput_ops_per_second",
    "replication",
    "support_oss_cluster_api",
    "modules",
}

DATABASE_FIELDS = {
    "dataset_size_in_gb",
    "redis_version",
    "throughput_ops_per_second",
    "replication",
    "enable_tls",
    "enable_default_user",
    "auto_minor_version_upgrade",
    "support_oss_cluster_api",
    "external_endpoint_for_oss_cluster_api",
    "persistence_mode",
    "data_eviction",
    "source_ips",
    "alerts",
    "remote_backup",
    "acl_rule_string",
    "acl_user_password_override",
    "tags",
    "enable_resource_tags",
}

AGENT_MEMORY_FIELDS = {
    "short_term_ttl_seconds",
    "long_term_ttl_seconds",
    "llm",
    "embedding",
    "extraction_cadence_seconds",
    "summarization",
    "custom_memory_types",
    "long_term_memory_exclusions",
    "tags",
}

AGENT_MEMORY_TERRAFORM_FIELDS = AGENT_MEMORY_FIELDS - {"llm", "embedding"}

MODEL_CONFIG_FIELDS = {
    "provider",
    "model",
    "credentials",
}

MODEL_CREDENTIALS_FIELDS = {
    "type",
    "api_key_env_var",
}

SENSITIVE_LITERAL_KEYS = {
    "api_key",
    "secret_key",
    "access_key",
    "password",
    "token",
    "provider_api_key",
    "acl_user_password_override",
}


class ConfigError(Exception):
    pass


def normalize_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError("Config root must be a JSON object.")

    return payload


def fail_unknown_fields(path: str, obj: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown field(s): {', '.join(unknown)}")


def require_object(path: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be an object.")
    return value


def optional_object(path: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return require_object(path, value)


def require_string(path: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string.")
    return value


def get_mode(path: str, obj: dict[str, Any]) -> str:
    mode = obj.get("mode", "managed")
    if mode not in MODE_VALUES:
        raise ConfigError(f"{path}.mode must be one of: {', '.join(sorted(MODE_VALUES))}.")
    return mode


def validate_key(path: str, value: str) -> None:
    if not KEY_PATTERN.fullmatch(value):
        raise ConfigError(
            f"{path} must contain only lowercase letters, numbers, hyphens, or underscores, "
            "start and end with a letter or number, and be at most 64 characters."
        )


def validate_normalized_name(path: str, value: str) -> str:
    normalized = normalize_name(value)
    if not NAME_PATTERN.fullmatch(normalized):
        raise ConfigError(
            f"{path} normalizes to {normalized!r}, but it must become a lowercase, "
            "hyphen-separated name that is 3 to 63 characters long."
        )
    return normalized


def walk_sensitive_literals(path: str, value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in SENSITIVE_LITERAL_KEYS and child not in (None, ""):
                raise ConfigError(
                    f"{child_path} looks like a secret literal. Store secret values outside git and use secret_ref."
                )
            walk_sensitive_literals(child_path, child)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_sensitive_literals(f"{path}[{index}]", child)


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: compact(child) for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [compact(child) for child in value]
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compact(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_fields(source: dict[str, Any], field_names: set[str]) -> dict[str, Any]:
    return {field: source[field] for field in sorted(field_names) if field in source}


def validate_env_var_name(path: str, value: str) -> None:
    if not ENV_VAR_PATTERN.fullmatch(value):
        raise ConfigError(f"{path} must be a valid environment variable name.")


def validate_model_config(path: str, value: Any) -> dict[str, Any]:
    model = require_object(path, value)
    fail_unknown_fields(path, model, MODEL_CONFIG_FIELDS)
    require_string(f"{path}.provider", model.get("provider"))
    require_string(f"{path}.model", model.get("model"))

    credentials = require_object(f"{path}.credentials", model.get("credentials"))
    fail_unknown_fields(f"{path}.credentials", credentials, MODEL_CREDENTIALS_FIELDS)
    credential_type = credentials.get("type", "apiKey")
    if credential_type != "apiKey":
        raise ConfigError(f"{path}.credentials.type must be apiKey.")
    env_var = require_string(f"{path}.credentials.api_key_env_var", credentials.get("api_key_env_var"))
    validate_env_var_name(f"{path}.credentials.api_key_env_var", env_var)
    return model


def render_model_config(
    store_path: str,
    block_name: str,
    model: dict[str, Any],
    tfvars: dict[str, Any],
    manifest_entry: dict[str, Any],
) -> dict[str, Any]:
    credentials = model["credentials"]
    api_key_env_var = credentials["api_key_env_var"]
    api_key = os.getenv(api_key_env_var)
    if not api_key:
        raise ConfigError(
            f"{store_path}.{block_name}.credentials.api_key_env_var references {api_key_env_var!r}, "
            "but that environment variable is not set."
        )

    tfvars[f"{block_name}_api_key"] = api_key
    manifest_entry["model_credential_env_vars"][block_name] = api_key_env_var
    return {
        "provider": model["provider"],
        "model": model["model"],
        "credentials": {
            "type": credentials.get("type", "apiKey"),
        },
    }


def load_and_validate(path: Path) -> dict[str, Any]:
    config = read_json(path)
    allowed_root = {
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

    subscription_key = require_string("$.subscription_key", config.get("subscription_key"))
    validate_key("$.subscription_key", subscription_key)

    subscription = require_object("$.subscription", config.get("subscription"))
    subscription_allowed = {"mode", "name", "subscription_id", "creation_plan"} | SUBSCRIPTION_FIELDS | SUBSCRIPTION_CREATION_PLAN_FIELDS
    fail_unknown_fields("$.subscription", subscription, subscription_allowed)
    subscription_mode = get_mode("$.subscription", subscription)
    subscription_name = validate_normalized_name("$.subscription.name", require_string("$.subscription.name", subscription.get("name")))
    subscription_id = subscription.get("subscription_id")
    if subscription_id is not None:
        if isinstance(subscription_id, bool) or not isinstance(subscription_id, int) or subscription_id <= 0:
            raise ConfigError("$.subscription.subscription_id must be a positive integer when provided.")
        if subscription_mode != "external":
            raise ConfigError("$.subscription.subscription_id is only valid when $.subscription.mode is external.")

    databases = optional_object("$.databases", config.get("databases"))
    for key, database in databases.items():
        validate_key(f"$.databases.{key}", key)
        database = require_object(f"$.databases.{key}", database)
        fail_unknown_fields(
            f"$.databases.{key}",
            database,
            {"mode", "name", "database_id", "agent_memory_compatible"} | DATABASE_FIELDS,
        )
        mode = get_mode(f"$.databases.{key}", database)
        if "name" in database:
            validate_normalized_name(f"$.databases.{key}.name", require_string(f"$.databases.{key}.name", database["name"]))
        elif mode == "managed":
            raise ConfigError(f"$.databases.{key}.name is required for managed databases.")
        if mode == "external" and "name" not in database and "database_id" not in database:
            raise ConfigError(f"$.databases.{key} must set name or database_id when mode is external.")

    agent_memory_stores = optional_object("$.agent_memory_stores", config.get("agent_memory_stores"))
    referenced_databases: set[str] = set()
    for key, store in agent_memory_stores.items():
        validate_key(f"$.agent_memory_stores.{key}", key)
        store = require_object(f"$.agent_memory_stores.{key}", store)
        fail_unknown_fields(
            f"$.agent_memory_stores.{key}",
            store,
            {"mode", "name", "database", "database_id", "api_keys"} | AGENT_MEMORY_FIELDS,
        )
        mode = get_mode(f"$.agent_memory_stores.{key}", store)
        if mode == "managed":
            validate_normalized_name(
                f"$.agent_memory_stores.{key}.name",
                require_string(f"$.agent_memory_stores.{key}.name", store.get("name")),
            )
            if "database" not in store and "database_id" not in store:
                raise ConfigError(f"$.agent_memory_stores.{key} must set database or database_id.")
            llm = store.get("llm")
            embedding = store.get("embedding")
            if (llm is None) != (embedding is None):
                raise ConfigError(f"$.agent_memory_stores.{key}.llm and embedding must be configured together.")
            if llm is not None:
                validate_model_config(f"$.agent_memory_stores.{key}.llm", llm)
                validate_model_config(f"$.agent_memory_stores.{key}.embedding", embedding)
                if "long_term_ttl_seconds" not in store:
                    raise ConfigError(
                        f"$.agent_memory_stores.{key}.long_term_ttl_seconds is required when embedding is configured."
                    )
        if "database" in store:
            database_key = require_string(f"$.agent_memory_stores.{key}.database", store["database"])
            if database_key not in databases:
                raise ConfigError(f"$.agent_memory_stores.{key}.database references unknown database {database_key!r}.")
            referenced_databases.add(database_key)
        api_keys = optional_object(f"$.agent_memory_stores.{key}.api_keys", store.get("api_keys"))
        for api_key_key, api_key in api_keys.items():
            validate_key(f"$.agent_memory_stores.{key}.api_keys.{api_key_key}", api_key_key)
            api_key = require_object(f"$.agent_memory_stores.{key}.api_keys.{api_key_key}", api_key)
            fail_unknown_fields(
                f"$.agent_memory_stores.{key}.api_keys.{api_key_key}",
                api_key,
                {"mode", "name", "enabled", "secret_ref"},
            )
            get_mode(f"$.agent_memory_stores.{key}.api_keys.{api_key_key}", api_key)
            if "name" in api_key:
                require_string(f"$.agent_memory_stores.{key}.api_keys.{api_key_key}.name", api_key["name"])

    for database_key in referenced_databases:
        database = databases[database_key]
        if subscription_mode == "managed" and subscription.get("public_endpoint_access") is not True:
            raise ConfigError(
                "$.subscription.public_endpoint_access must be true because Agent Memory public preview "
                "requires the backing database to have a public endpoint."
            )
        if get_mode(f"$.databases.{database_key}", database) != "managed":
            continue
        compatible = bool(database.get("agent_memory_compatible", False))
        default_user = database.get("enable_default_user")
        if default_user is False:
            raise ConfigError(
                f"$.databases.{database_key}.enable_default_user must be true because Agent Memory uses this database."
            )
        if default_user is not True and not compatible:
            raise ConfigError(
                f"$.databases.{database_key} is used by Agent Memory. Set agent_memory_compatible=true "
                "or enable_default_user=true."
            )

    walk_sensitive_literals("$", config)

    config["_normalized"] = {
        "subscription_name": subscription_name,
        "subscription_id": subscription_id,
        "subscription_mode": subscription_mode,
        "referenced_databases": sorted(referenced_databases),
    }
    return config


def render_subscription(config: dict[str, Any], out_dir: Path, manifest: dict[str, Any]) -> None:
    subscription = config["subscription"]
    normalized = config["_normalized"]
    if normalized["subscription_mode"] != "managed":
        return

    creation_plan = optional_object("$.subscription.creation_plan", subscription.get("creation_plan"))
    tfvars = {
        "subscription_name": normalized["subscription_name"],
        **copy_fields(subscription, SUBSCRIPTION_FIELDS),
        **copy_fields(subscription, SUBSCRIPTION_CREATION_PLAN_FIELDS),
        **copy_fields(creation_plan, SUBSCRIPTION_CREATION_PLAN_FIELDS),
    }

    path = out_dir / "subscription.auto.tfvars.json"
    write_json(path, tfvars)
    manifest["subscription"]["tfvars_path"] = str(path)
    manifest["subscription"]["state_key"] = f"subscriptions/{config['subscription_key']}.tfstate"


def render_database(
    config: dict[str, Any],
    database_key: str,
    database: dict[str, Any],
    out_dir: Path,
    manifest: dict[str, Any],
) -> None:
    mode = get_mode(f"$.databases.{database_key}", database)
    database_name = normalize_name(database["name"]) if "name" in database else None
    entry = {
        "key": database_key,
        "mode": mode,
        "name": database_name,
        "database_id": database.get("database_id"),
        "state_key": f"databases/{config['subscription_key']}/{database_key}.tfstate",
    }

    if mode != "managed":
        manifest["databases"].append(entry)
        return

    tfvars = {
        "subscription_name": config["_normalized"]["subscription_name"],
        "database_name": database_name,
        **copy_fields(database, DATABASE_FIELDS),
    }
    if config["_normalized"]["subscription_id"] is not None:
        tfvars["subscription_id"] = config["_normalized"]["subscription_id"]
    if database.get("agent_memory_compatible") and "enable_default_user" not in tfvars:
        tfvars["enable_default_user"] = True

    path = out_dir / f"database-{database_key}.auto.tfvars.json"
    write_json(path, tfvars)
    entry["tfvars_path"] = str(path)
    manifest["databases"].append(entry)


def render_agent_memory(
    config: dict[str, Any],
    store_key: str,
    store: dict[str, Any],
    out_dir: Path,
    manifest: dict[str, Any],
) -> None:
    mode = get_mode(f"$.agent_memory_stores.{store_key}", store)
    store_name = normalize_name(store["name"]) if "name" in store else None
    entry = {
        "key": store_key,
        "mode": mode,
        "name": store_name,
        "database_key": store.get("database"),
        "state_key": f"agent-memory/{config['subscription_key']}/{store_key}.tfstate",
        "api_key_secret_refs": {},
        "model_credential_env_vars": {},
    }

    api_keys = optional_object(f"$.agent_memory_stores.{store_key}.api_keys", store.get("api_keys"))
    for api_key_key, api_key in api_keys.items():
        if "secret_ref" in api_key:
            entry["api_key_secret_refs"][api_key_key] = api_key["secret_ref"]

    if mode != "managed":
        manifest["agent_memory_stores"].append(entry)
        return

    tfvars = {
        "subscription_name": config["_normalized"]["subscription_name"],
        "agent_memory_name": store_name,
        **copy_fields(store, AGENT_MEMORY_TERRAFORM_FIELDS),
    }
    if config["_normalized"]["subscription_id"] is not None:
        tfvars["subscription_id"] = config["_normalized"]["subscription_id"]

    if "llm" in store:
        tfvars["llm"] = render_model_config(
            f"$.agent_memory_stores.{store_key}",
            "llm",
            store["llm"],
            tfvars,
            entry,
        )
        tfvars["embedding"] = render_model_config(
            f"$.agent_memory_stores.{store_key}",
            "embedding",
            store["embedding"],
            tfvars,
            entry,
        )

    if "database_id" in store:
        tfvars["database_id"] = store["database_id"]
    else:
        database = config["databases"][store["database"]]
        if "database_id" in database and "name" not in database:
            tfvars["database_id"] = database["database_id"]
        else:
            tfvars["database_name"] = normalize_name(database["name"])

    managed_api_keys = {}
    for api_key_key, api_key in api_keys.items():
        if get_mode(f"$.agent_memory_stores.{store_key}.api_keys.{api_key_key}", api_key) != "managed":
            continue
        managed_api_keys[api_key_key] = {
            "name": api_key.get("name", api_key_key),
            "enabled": api_key.get("enabled", True),
        }
    if managed_api_keys:
        tfvars["api_keys"] = managed_api_keys

    path = out_dir / f"agent-memory-{store_key}.auto.tfvars.json"
    write_json(path, tfvars)
    entry["tfvars_path"] = str(path)
    manifest["agent_memory_stores"].append(entry)


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
            "state_key": f"subscriptions/{config['subscription_key']}.tfstate",
        },
        "databases": [],
        "agent_memory_stores": [],
    }


def render(config_path: Path, out_dir: Path) -> dict[str, Any]:
    config = load_and_validate(config_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(config, config_path)

    render_subscription(config, out_dir, manifest)

    for database_key, database in config.get("databases", {}).items():
        render_database(config, database_key, database, out_dir, manifest)

    for store_key, store in config.get("agent_memory_stores", {}).items():
        render_agent_memory(config, store_key, store, out_dir, manifest)

    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, manifest)
    return manifest


def validate_command(args: argparse.Namespace) -> None:
    config = load_and_validate(args.config)
    print(
        json.dumps(
            {
                "valid": True,
                "customer": config["customer"],
                "environment": config["environment"],
                "subscription_key": config["subscription_key"],
                "subscription_name": config["_normalized"]["subscription_name"],
                "databases": len(config.get("databases", {})),
                "agent_memory_stores": len(config.get("agent_memory_stores", {})),
            },
            indent=2,
            sort_keys=True,
        )
    )


def render_command(args: argparse.Namespace) -> None:
    manifest = render(args.config, args.out_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and render Redis Cloud subscription config files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a subscription config file.")
    validate_parser.add_argument("--config", required=True, type=Path)
    validate_parser.set_defaults(func=validate_command)

    render_parser = subparsers.add_parser("render", help="Render Terraform tfvars and a manifest from a config file.")
    render_parser.add_argument("--config", required=True, type=Path)
    render_parser.add_argument("--out-dir", required=True, type=Path)
    render_parser.set_defaults(func=render_command)

    args = parser.parse_args()
    try:
        args.func(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
