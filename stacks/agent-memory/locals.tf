# Display names are normalized before validation: lower-case, replace runs of
# non-alphanumeric characters with "-", collapse hyphens, then trim their ends.
# Example: "Support Agent" becomes "support-agent". JSON map/state keys do not
# pass through this expression and must stay stable when a display name changes.
locals {
  subscription_name = var.subscription_name == null ? null : trim(
    replace(
      replace(lower(trimspace(var.subscription_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

  # Parent selection: database_id skips both lookups; subscription_id plus a
  # database name needs only the database lookup; names alone require both.
  # Each [0] below is used only when its matching count-created lookup exists.
  lookup_database     = var.database_id == null
  lookup_subscription = local.lookup_database && var.subscription_id == null
  resolved_subscription_id = local.lookup_database ? (
    local.lookup_subscription ? data.rediscloud_subscription.target[0].id : var.subscription_id
  ) : null

  database_name = var.database_name == null ? null : trim(
    replace(
      replace(lower(trimspace(var.database_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

  agent_memory_name = trim(
    replace(
      replace(lower(trimspace(var.agent_memory_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

  # Keep enabled entries under their original map keys so adding a sibling
  # cannot shift existing Terraform resource addresses. False removes/revokes it.
  enabled_api_keys = {
    for key, value in var.api_keys : key => value
    if try(value.enabled, true)
  }

  resolved_database_id = local.lookup_database ? data.rediscloud_database.target[0].db_id : var.database_id
}
