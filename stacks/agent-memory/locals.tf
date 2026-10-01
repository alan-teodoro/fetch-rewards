locals {
  subscription_name = var.subscription_name == null ? null : trim(
    replace(
      replace(lower(trimspace(var.subscription_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

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

  enabled_api_keys = {
    for key, value in var.api_keys : key => value
    if try(value.enabled, true)
  }

  resolved_database_id = local.lookup_database ? data.rediscloud_database.target[0].db_id : var.database_id
}
