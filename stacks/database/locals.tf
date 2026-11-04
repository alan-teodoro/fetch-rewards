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

  database_name = trim(
    replace(
      replace(lower(trimspace(var.database_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

  # A direct subscription ID avoids a name lookup but does not create/adopt
  # the subscription. This stack owns only its database and application ACLs.
  lookup_subscription      = var.lookup_subscription != null ? var.lookup_subscription : var.subscription_id == null
  resolved_subscription_id = local.lookup_subscription ? data.rediscloud_subscription.target[0].id : var.subscription_id

  throughput_measurement_by = "operations-per-second"

  # Account-wide ACL names are derived from the database name. Use database
  # names unique across managed subscriptions in the same Redis Cloud account.
  acl_rule_name = "acl-${local.database_name}"
  acl_role_name = "role-${local.database_name}"
  acl_user_name = "svc-${local.database_name}"

  # An explicit password means random_password has count = 0, so try() makes
  # its missing [0] harmless. coalesce() selects the override or generated secret.
  generated_acl_user_password = try(
    random_password.acl_user[0].result,
    null
  )

  acl_user_password = coalesce(var.acl_user_password_override, local.generated_acl_user_password)

  # Tagging is opt-in for accounts that support it. null leaves the attribute
  # unset; an enabled map combines defaults with caller overrides and normalizes
  # keys/values to the form expected by Redis Cloud.
  tags = var.enable_resource_tags ? {
    for key, value in merge(
      {
        managed_by = "terraform"
        component  = "redis-cloud-database"
      },
      var.tags
    ) : lower(key) => lower(tostring(value))
  } : null
}
