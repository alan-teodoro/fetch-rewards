"""Stack identities, state paths and lifecycle ordering."""

from __future__ import annotations

from typing import Any


CREATE_ORDER = ("subscription", "database", "agent-memory")
DESTROY_ORDER = tuple(reversed(CREATE_ORDER))
STACKS = set(CREATE_ORDER)


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
    },
}


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


def subscription_state_prefix(config: dict[str, Any]) -> str:
    return f"subscriptions/{config['subscription_key']}"


def subscription_state_key(config: dict[str, Any]) -> str:
    return f"{subscription_state_prefix(config)}/subscription.tfstate"


def database_state_key(config: dict[str, Any], database_key: str) -> str:
    return f"{subscription_state_prefix(config)}/databases/{database_key}.tfstate"


def agent_memory_state_key(config: dict[str, Any], store_key: str) -> str:
    return f"{subscription_state_prefix(config)}/agent-memory/{store_key}.tfstate"


def entries(manifest, phase):
    result = []
    subscription = manifest["subscription"]
    if subscription["mode"] == "managed":
        result.append(("subscription", subscription))
    result += [("database", item) for item in manifest["databases"] if item["mode"] == "managed"]
    result += [
        ("agent-memory", item)
        for item in manifest["agent_memory_stores"]
        if item["mode"] == "managed"
    ]
    if phase == "destroy":
        # Reverse phases, preserve the stable order of siblings.
        return sorted(result, key=lambda entry: DESTROY_ORDER.index(entry[0]))
    return (
        result
        if phase in {"preview", "rollout"}
        else [entry for entry in result if entry[0] == phase]
    )
