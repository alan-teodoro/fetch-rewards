locals {
  cloud_provider               = var.cloud_provider
  region                       = var.region
  networking_deployment_cidr   = var.networking_deployment_cidr
  multiple_availability_zones  = var.multiple_availability_zones
  preferred_availability_zones = var.preferred_availability_zones
  public_endpoint_access       = var.public_endpoint_access
  memory_storage               = var.memory_storage
  use_marketplace              = var.payment_method == "marketplace"
  use_credit_card              = var.payment_method == "credit-card"
  can_lookup_payment_card      = local.use_credit_card && var.payment_method_id == null && var.payment_card_type != null && var.payment_card_last_four != null
  resolved_payment_method_id   = local.use_credit_card ? coalesce(var.payment_method_id, try(data.rediscloud_payment_method.card[0].id, null)) : null
  throughput_measurement_by    = "operations-per-second"
  replication                  = var.replication
  support_oss_cluster_api      = var.support_oss_cluster_api
  modules                      = var.modules

  tags = {
    for key, value in merge(
      {
        managed_by = "terraform"
        customer   = "fetch-rewards"
        component  = "redis-cloud-subscription"
      },
      var.tags
    ) : lower(key) => lower(tostring(value))
  }
}
