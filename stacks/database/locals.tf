locals {
  subscription_name = trim(
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

  throughput_measurement_by = "operations-per-second"

  acl_rule_name = "acl-${local.database_name}"
  acl_role_name = "role-${local.database_name}"
  acl_user_name = "svc-${local.database_name}"

  generated_acl_user_password = try(
    random_password.acl_user[0].result,
    null
  )

  acl_user_password = coalesce(var.acl_user_password_override, local.generated_acl_user_password)

  tags = var.enable_resource_tags ? {
    for key, value in merge(
      {
        managed_by = "terraform"
        customer   = "fetch-rewards"
        component  = "redis-cloud-database"
      },
      var.tags
    ) : lower(key) => lower(tostring(value))
  } : null
}
