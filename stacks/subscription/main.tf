resource "rediscloud_subscription" "this" {
  name                   = var.subscription_name
  payment_method         = local.payment_method
  payment_method_id      = local.payment_method_id
  public_endpoint_access = local.public_endpoint_access
  memory_storage         = local.memory_storage

  cloud_provider {
    provider      = local.cloud_provider
    resource_tags = local.tags

    region {
      region                       = local.region
      multiple_availability_zones  = local.multiple_availability_zones
      networking_deployment_cidr   = local.networking_deployment_cidr
      preferred_availability_zones = local.preferred_availability_zones
    }
  }

  creation_plan {
    dataset_size_in_gb           = var.dataset_size_in_gb
    quantity                     = 1
    replication                  = local.replication
    support_oss_cluster_api      = local.support_oss_cluster_api
    throughput_measurement_by    = local.throughput_measurement_by
    throughput_measurement_value = var.throughput_ops_per_second
    modules                      = local.modules
  }

  dynamic "maintenance_windows" {
    for_each = var.maintenance_windows == null ? [] : [var.maintenance_windows]

    content {
      mode = maintenance_windows.value.mode

      dynamic "window" {
        for_each = maintenance_windows.value.window == null ? [] : [maintenance_windows.value.window]

        content {
          start_hour        = window.value.start_hour
          duration_in_hours = window.value.duration_in_hours
          days              = window.value.days
        }
      }
    }
  }
}
