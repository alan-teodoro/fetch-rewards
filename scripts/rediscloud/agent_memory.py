"""Agent Memory configuration inputs and model credential rendering."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config_common import (
    ConfigError,
    copy_fields,
    fail_unknown_fields,
    get_mode,
    normalize_name,
    optional_object,
    require_object,
    require_string,
    validate_env_var_name,
    validate_key,
    validate_normalized_name,
    write_json,
)
from .stacks import agent_memory_state_key

AGENT_MEMORY_FIELDS = {
    "short_term_ttl_seconds",
    "long_term_ttl_seconds",
    "llm",
    "embedding",
    "extraction_cadence_seconds",
    "extraction_strategy",
    "timeouts",
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
    "api_key_version",
}


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
    env_var = require_string(
        f"{path}.credentials.api_key_env_var", credentials.get("api_key_env_var")
    )
    validate_env_var_name(f"{path}.credentials.api_key_env_var", env_var)
    version = credentials.get("api_key_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ConfigError(f"{path}.credentials.api_key_version must be a positive integer.")
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
            "api_key_version": credentials.get("api_key_version", 1),
        },
    }


def validate_custom_memory_types(path: str, memory_types: Any) -> None:
    if not isinstance(memory_types, list):
        raise ConfigError(f"{path} must be a list.")
    for index, memory_type in enumerate(memory_types):
        memory_path = f"{path}[{index}]"
        memory_type = require_object(memory_path, memory_type)
        require_string(f"{memory_path}.name", memory_type.get("name"))
        require_string(f"{memory_path}.description", memory_type.get("description"))
        fields = memory_type.get("fields", [])
        if not isinstance(fields, list):
            raise ConfigError(f"{memory_path}.fields must be a list.")
        for field_index, field in enumerate(fields):
            field_path = f"{memory_path}.fields[{field_index}]"
            field = require_object(field_path, field)
            require_string(f"{field_path}.name", field.get("name"))
            require_string(
                f"{field_path}.description", field.get("description")
            )
            require_string(f"{field_path}.type", field.get("type"))


def validate_api_keys(path: str, value: Any) -> None:
    api_keys = optional_object(path, value)
    for api_key_key, api_key in api_keys.items():
        validate_key(f"{path}.{api_key_key}", api_key_key)
        api_key = require_object(f"{path}.{api_key_key}", api_key)
        fail_unknown_fields(
            f"{path}.{api_key_key}",
            api_key,
            {"mode", "name", "enabled", "secret_ref", "timeouts"},
        )
        get_mode(f"{path}.{api_key_key}", api_key)
        if "name" in api_key:
            require_string(f"{path}.{api_key_key}.name", api_key["name"])


def validate_agent_memory_stores(stores: dict[str, Any], databases: dict[str, Any]) -> set[str]:
    referenced_databases: set[str] = set()
    for key, store in stores.items():
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
            if "database" in store and "database_id" in store:
                raise ConfigError(f"$.agent_memory_stores.{key} must set only one of database or database_id.")
            llm = store.get("llm")
            embedding = store.get("embedding")
            if (llm is None) != (embedding is None):
                raise ConfigError(
                    f"$.agent_memory_stores.{key}.llm and embedding must be configured together."
                )
            if llm is not None:
                validate_model_config(f"$.agent_memory_stores.{key}.llm", llm)
                validate_model_config(f"$.agent_memory_stores.{key}.embedding", embedding)
                if store.get("long_term_ttl_seconds") is None:
                    raise ConfigError(
                        f"$.agent_memory_stores.{key}.long_term_ttl_seconds is required when embedding is configured."
                    )
        if "database" in store:
            database_key = require_string(
                f"$.agent_memory_stores.{key}.database", store["database"]
            )
            if database_key not in databases:
                raise ConfigError(
                    f"$.agent_memory_stores.{key}.database references unknown database {database_key!r}."
                )
            referenced_databases.add(database_key)
        validate_custom_memory_types(
            f"$.agent_memory_stores.{key}.custom_memory_types", store.get("custom_memory_types", [])
        )
        validate_api_keys(f"$.agent_memory_stores.{key}.api_keys", store.get("api_keys"))
    return referenced_databases


def validate_agent_memory_databases(
    subscription: dict[str, Any],
    subscription_mode: str,
    databases: dict[str, Any],
    referenced_databases: set[str],
) -> None:
    for database_key in referenced_databases:
        database = databases[database_key]
        if (
            subscription_mode == "managed"
            and subscription.get("public_endpoint_access") is not True
        ):
            raise ConfigError(
                "$.subscription.public_endpoint_access must be true because Agent Memory public preview "
                "requires the backing database to have a public endpoint."
            )
        if get_mode(f"$.databases.{database_key}", database) != "managed":
            continue
        if database.get("enable_tls") is False:
            raise ConfigError(
                f"$.databases.{database_key}.enable_tls must be true because Agent Memory uses this database."
            )
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
        "database_id": store.get(
            "database_id",
            config.get("databases", {}).get(store.get("database"), {}).get("database_id"),
        ),
        "state_key": agent_memory_state_key(config, store_key),
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

    if store.get("llm") is not None:
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
        if "database_id" in database:
            tfvars["database_id"] = database["database_id"]
        else:
            tfvars["database_name"] = normalize_name(database["name"])

    managed_api_keys = {}
    for api_key_key, api_key in api_keys.items():
        if (
            get_mode(f"$.agent_memory_stores.{store_key}.api_keys.{api_key_key}", api_key)
            != "managed"
        ):
            continue
        managed_api_keys[api_key_key] = {
            "name": api_key.get("name", api_key_key),
            "enabled": api_key.get("enabled", True),
            **copy_fields(api_key, {"timeouts"}),
        }
    if managed_api_keys:
        tfvars["api_keys"] = managed_api_keys

    path = out_dir / f"agent-memory-{store_key}.auto.tfvars.json"
    write_json(path, tfvars)
    entry["tfvars_path"] = str(path)
    manifest["agent_memory_stores"].append(entry)
