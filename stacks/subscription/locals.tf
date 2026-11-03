# Display names are normalized before validation: lower-case, replace runs of
# non-alphanumeric characters with "-", collapse hyphens, then trim their ends.
# Example: "Support Agent" becomes "support-agent". JSON map/state keys do not
# pass through this expression and must stay stable when a display name changes.
locals {
  subscription_name = trim(
    replace(
      replace(lower(trimspace(var.subscription_name)), "/[^a-z0-9]+/", "-"),
      "/-+/",
      "-"
    ),
    "-"
  )

  cloud_provider               = var.cloud_provider
  region                       = var.region
  networking_deployment_cidr   = var.networking_deployment_cidr
  multiple_availability_zones  = var.multiple_availability_zones
  preferred_availability_zones = var.preferred_availability_zones
  public_endpoint_access       = var.public_endpoint_access
  memory_storage               = var.memory_storage
  # Explicit ID wins over card lookup. Marketplace billing sends its selector
  # instead of a card ID; null attributes are left for the provider/API to handle.
  use_marketplace            = var.payment_method == "marketplace"
  use_credit_card            = var.payment_method == "credit-card"
  can_lookup_payment_card    = local.use_credit_card && var.payment_method_id == null && var.payment_card_type != null && var.payment_card_last_four != null
  resolved_payment_method_id = local.use_credit_card ? (var.payment_method_id != null ? var.payment_method_id : try(data.rediscloud_payment_method.card[0].id, null)) : null
  throughput_measurement_by  = "operations-per-second"
  replication                = var.replication
  support_oss_cluster_api    = var.support_oss_cluster_api
  modules                    = var.modules

  # Tagging is opt-in for accounts that support it. null leaves the attribute
  # unset; an enabled map combines defaults with caller overrides and normalizes
  # keys/values to the form expected by Redis Cloud.
  tags = var.enable_resource_tags ? {
    for key, value in merge(
      {
        managed_by = "terraform"
        component  = "redis-cloud-subscription"
      },
      var.tags
    ) : lower(key) => lower(tostring(value))
  } : null
}
