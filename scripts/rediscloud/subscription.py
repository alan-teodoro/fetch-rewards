"""Subscription configuration validation and Terraform input rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_common import (
    ConfigError,
    copy_fields,
    fail_unknown_fields,
    get_mode,
    optional_object,
    require_string,
    validate_normalized_name,
    write_json,
)
from .stacks import subscription_state_key

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


def validate_subscription(subscription: dict[str, Any]) -> tuple[str, str, int | None]:
    subscription_allowed = (
        {"mode", "name", "subscription_id", "creation_plan"}
        | SUBSCRIPTION_FIELDS
        | SUBSCRIPTION_CREATION_PLAN_FIELDS
    )
    fail_unknown_fields("$.subscription", subscription, subscription_allowed)
    subscription_mode = get_mode("$.subscription", subscription)
    if (
        subscription_mode == "managed"
        and subscription.get("payment_method", "credit-card") == "credit-card"
        and not subscription.get("payment_method_id")
        and not (subscription.get("payment_card_type") and subscription.get("payment_card_last_four"))
    ):
        raise ConfigError("$.subscription: set payment_method_id or both payment_card_type and payment_card_last_four for credit-card billing.")
    subscription_name = validate_normalized_name(
        "$.subscription.name", require_string("$.subscription.name", subscription.get("name"))
    )
    subscription_id = subscription.get("subscription_id")
    if subscription_id is not None:
        if (
            isinstance(subscription_id, bool)
            or not isinstance(subscription_id, int)
            or subscription_id <= 0
        ):
            raise ConfigError(
                "$.subscription.subscription_id must be a positive integer when provided."
            )
        if subscription_mode != "external":
            raise ConfigError(
                "$.subscription.subscription_id is only valid when $.subscription.mode is external."
            )

    return subscription_mode, subscription_name, subscription_id


def render_subscription(config: dict[str, Any], out_dir: Path, manifest: dict[str, Any]) -> None:
    subscription = config["subscription"]
    normalized = config["_normalized"]
    if normalized["subscription_mode"] != "managed":
        return

    creation_plan = optional_object(
        "$.subscription.creation_plan", subscription.get("creation_plan")
    )
    tfvars = {
        "subscription_name": normalized["subscription_name"],
        **copy_fields(subscription, SUBSCRIPTION_FIELDS),
        **copy_fields(subscription, SUBSCRIPTION_CREATION_PLAN_FIELDS),
        **copy_fields(creation_plan, SUBSCRIPTION_CREATION_PLAN_FIELDS),
    }

    path = out_dir / "subscription.auto.tfvars.json"
    write_json(path, tfvars)
    manifest["subscription"]["tfvars_path"] = str(path)
    manifest["subscription"]["state_key"] = subscription_state_key(config)
