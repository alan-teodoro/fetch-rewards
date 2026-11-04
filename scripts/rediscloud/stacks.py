"""One JSON, one deployment root and one durable backend key."""

from __future__ import annotations

STACKS = {"deployment"}

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


def deployment_state_key(config):
    return f"subscriptions/{config['subscription_key']}/terraform.tfstate"
