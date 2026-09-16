locals {
  throughput_measurement_by = "operations-per-second"

  acl_rule_name = "acl-${var.database_name}"
  acl_role_name = "role-${var.database_name}"
  acl_user_name = "svc-${var.database_name}"

  generated_acl_user_password = try(
    random_password.acl_user[0].result,
    null
  )

  acl_user_password = coalesce(var.acl_user_password_override, local.generated_acl_user_password)

  tags = {
    for key, value in merge(
      {
        managed_by = "terraform"
        customer   = "fetch-rewards"
        component  = "redis-cloud-database"
      },
      var.tags
    ) : lower(key) => lower(tostring(value))
  }
}
