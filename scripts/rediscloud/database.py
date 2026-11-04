"""Database configuration validation and Terraform input rendering."""

from __future__ import annotations

from typing import Any

from .config_common import (
    ConfigError,
    copy_fields,
    fail_unknown_fields,
    get_mode,
    normalize_name,
    require_object,
    require_string,
    validate_key,
    validate_normalized_name,
)

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


DATABASE_ALERT_NAMES = {
    "dataset-size",
    "throughput-higher-than",
    "throughput-lower-than",
    "latency",
    "syncsource-error",
    "syncsource-lag",
}


def validate_databases(databases: dict[str, Any]) -> None:
    for key, database in databases.items():
        validate_key(f"$.databases.{key}", key)
        database = require_object(f"$.databases.{key}", database)
        fail_unknown_fields(
            f"$.databases.{key}",
            database,
            {"mode", "name", "database_id", "agent_memory_compatible"}
            | DATABASE_FIELDS,
        )
        mode = get_mode(f"$.databases.{key}", database)
        if mode == "managed" and "database_id" in database:
            raise ConfigError(
                f"$.databases.{key}.database_id is only valid when mode is external."
            )
        if "name" in database:
            validate_normalized_name(
                f"$.databases.{key}.name",
                require_string(f"$.databases.{key}.name", database["name"]),
            )
        elif mode == "managed":
            raise ConfigError(
                f"$.databases.{key}.name is required for managed databases."
            )
        if (
            mode == "external"
            and "name" not in database
            and "database_id" not in database
        ):
            raise ConfigError(
                f"$.databases.{key} must set name or database_id when mode is external."
            )
        alerts = database.get("alerts", [])
        if not isinstance(alerts, list):
            raise ConfigError(f"$.databases.{key}.alerts must be a list.")
        for index, alert in enumerate(alerts):
            alert = require_object(f"$.databases.{key}.alerts[{index}]", alert)
            alert_name = require_string(
                f"$.databases.{key}.alerts[{index}].name", alert.get("name")
            )
            if alert_name not in DATABASE_ALERT_NAMES:
                raise ConfigError(
                    f"$.databases.{key}.alerts[{index}].name must be one of: "
                    f"{', '.join(sorted(DATABASE_ALERT_NAMES))}."
                )


def render_database(
    config: dict[str, Any],
    database_key: str,
    database: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    mode = get_mode(f"$.databases.{database_key}", database)
    database_name = normalize_name(database["name"]) if "name" in database else None
    entry = {
        "key": database_key,
        "mode": mode,
        "name": database_name,
        "database_id": database.get("database_id"),
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

    entry["inputs"] = tfvars
    manifest["databases"].append(entry)
