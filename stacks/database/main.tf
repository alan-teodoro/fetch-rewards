resource "terraform_data" "validation" {
  lifecycle {
    precondition {
      condition     = !var.external_endpoint_for_oss_cluster_api || var.support_oss_cluster_api
      error_message = "external_endpoint_for_oss_cluster_api requires support_oss_cluster_api to be true."
    }
  }
}

data "rediscloud_subscription" "target" {
  name = var.subscription_name
}

# Use random_password for generated credentials so Terraform treats the result
# as sensitive throughout plans, applies, and outputs. The value is still stored
# in Terraform state, so the remote state bucket must remain restricted.
resource "random_password" "acl_user" {
  count = var.acl_user_password_override == null ? 1 : 0

  length           = 26
  upper            = true
  lower            = true
  numeric          = true
  special          = true
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "!"
}

resource "rediscloud_subscription_database" "this" {
  depends_on = [terraform_data.validation]

  subscription_id                       = data.rediscloud_subscription.target.id
  name                                  = var.database_name
  dataset_size_in_gb                    = var.dataset_size_in_gb
  redis_version                         = var.redis_version
  throughput_measurement_by             = local.throughput_measurement_by
  throughput_measurement_value          = var.throughput_ops_per_second
  data_persistence                      = var.persistence_mode
  data_eviction                         = var.data_eviction
  replication                           = var.replication
  enable_tls                            = var.enable_tls
  enable_default_user                   = var.enable_default_user
  support_oss_cluster_api               = var.support_oss_cluster_api
  external_endpoint_for_oss_cluster_api = var.external_endpoint_for_oss_cluster_api
  auto_minor_version_upgrade            = var.auto_minor_version_upgrade
  source_ips                            = var.source_ips
  tags                                  = local.tags

  dynamic "alert" {
    for_each = var.alerts

    content {
      name  = alert.value.name
      value = alert.value.value
    }
  }

  dynamic "remote_backup" {
    for_each = var.remote_backup == null ? [] : [var.remote_backup]

    content {
      interval     = remote_backup.value.interval
      time_utc     = remote_backup.value.time_utc
      storage_type = remote_backup.value.storage_type
      storage_path = remote_backup.value.storage_path
    }
  }
}

resource "rediscloud_acl_rule" "this" {
  name = local.acl_rule_name
  rule = var.acl_rule_string
}

resource "rediscloud_acl_role" "this" {
  name = local.acl_role_name

  rule {
    name = rediscloud_acl_rule.this.name

    database {
      subscription = data.rediscloud_subscription.target.id
      database     = rediscloud_subscription_database.this.db_id
    }
  }
}

resource "rediscloud_acl_user" "this" {
  name     = local.acl_user_name
  role     = rediscloud_acl_role.this.name
  password = local.acl_user_password
}
