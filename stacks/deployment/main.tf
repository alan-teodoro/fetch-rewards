# Only resources declared managed are owned by this state. External parents are
# resolved through data sources, never imported or scheduled for destruction.
data "rediscloud_subscription" "external" {
  count = var.subscription.mode == "external" && var.subscription.subscription_id == null ? 1 : 0
  name  = var.subscription.subscription_name
}
locals {
  # Ownership mode is known during planning; the managed ID may be unknown.
  subscription_id = var.subscription.mode == "managed" ? module.subscription[0].subscription_id : (
    var.subscription.subscription_id != null ? var.subscription.subscription_id : data.rediscloud_subscription.external[0].id
  )
  managed_databases         = { for key, value in var.databases : key => value if value.mode == "managed" }
  managed_agents            = { for key, value in var.agent_memory_stores : key => value if value.mode == "managed" }
  external_database_lookups = { for key, value in var.databases : key => value if value.mode == "external" && value.database_id == null }
}

data "rediscloud_database" "external" {
  for_each        = local.external_database_lookups
  subscription_id = local.subscription_id
  name            = each.value.database_name
}
# Stable map keys connect every store to its declared managed/external database.
locals {
  database_ids = merge(
    { for key, value in module.database : key => value.database_id },
    { for key, value in var.databases : key => (value.database_id != null ? value.database_id : data.rediscloud_database.external[key].db_id) if value.mode == "external" }
  )
}

# The ID references below let Terraform order creation and destruction itself.
module "subscription" {
  source                       = "../subscription"
  count                        = var.subscription.mode == "managed" ? 1 : 0
  subscription_name            = var.subscription.subscription_name
  dataset_size_in_gb           = var.subscription.dataset_size_in_gb
  cloud_provider               = var.subscription.cloud_provider
  region                       = var.subscription.region
  networking_deployment_cidr   = var.subscription.networking_deployment_cidr
  multiple_availability_zones  = var.subscription.multiple_availability_zones
  preferred_availability_zones = var.subscription.preferred_availability_zones
  public_endpoint_access       = var.subscription.public_endpoint_access
  memory_storage               = var.subscription.memory_storage
  payment_method               = var.subscription.payment_method
  payment_method_id            = var.subscription.payment_method_id
  payment_card_type            = var.subscription.payment_card_type
  payment_card_last_four       = var.subscription.payment_card_last_four
  throughput_ops_per_second    = var.subscription.throughput_ops_per_second
  replication                  = var.subscription.replication
  support_oss_cluster_api      = var.subscription.support_oss_cluster_api
  modules                      = var.subscription.modules
  maintenance_windows          = var.subscription.maintenance_windows
  tags                         = var.subscription.tags
  enable_resource_tags         = var.subscription.enable_resource_tags
}

# The ID references below let Terraform order creation and destruction itself.
module "database" {
  source                                = "../database"
  for_each                              = local.managed_databases
  subscription_id                       = local.subscription_id
  subscription_name                     = var.subscription.subscription_name
  lookup_subscription                   = false
  database_name                         = each.value.database_name
  dataset_size_in_gb                    = each.value.dataset_size_in_gb
  redis_version                         = each.value.redis_version
  throughput_ops_per_second             = each.value.throughput_ops_per_second
  replication                           = each.value.replication
  enable_tls                            = each.value.enable_tls
  enable_default_user                   = each.value.enable_default_user
  auto_minor_version_upgrade            = each.value.auto_minor_version_upgrade
  support_oss_cluster_api               = each.value.support_oss_cluster_api
  external_endpoint_for_oss_cluster_api = each.value.external_endpoint_for_oss_cluster_api
  persistence_mode                      = each.value.persistence_mode
  data_eviction                         = each.value.data_eviction
  source_ips                            = each.value.source_ips
  alerts                                = each.value.alerts
  remote_backup                         = each.value.remote_backup
  acl_rule_string                       = each.value.acl_rule_string
  acl_user_password_override            = each.value.acl_user_password_override
  tags                                  = each.value.tags
  enable_resource_tags                  = each.value.enable_resource_tags
}

# The ID references below let Terraform order creation and destruction itself.
module "agent_memory" {
  source                      = "../agent-memory"
  for_each                    = local.managed_agents
  subscription_id             = local.subscription_id
  subscription_name           = var.subscription.subscription_name
  lookup_database             = false
  database_id                 = each.value.database_id != null ? each.value.database_id : local.database_ids[each.value.database_key]
  llm_api_key                 = try(var.model_api_keys[each.key].llm_api_key, null)
  embedding_api_key           = try(var.model_api_keys[each.key].embedding_api_key, null)
  agent_memory_name           = each.value.agent_memory_name
  short_term_ttl_seconds      = each.value.short_term_ttl_seconds
  long_term_ttl_seconds       = each.value.long_term_ttl_seconds
  extraction_cadence_seconds  = each.value.extraction_cadence_seconds
  extraction_strategy         = each.value.extraction_strategy
  timeouts                    = each.value.timeouts
  llm                         = each.value.llm
  embedding                   = each.value.embedding
  summarization               = each.value.summarization
  custom_memory_types         = each.value.custom_memory_types
  long_term_memory_exclusions = each.value.long_term_memory_exclusions
  api_keys                    = each.value.api_keys
  tags                        = each.value.tags
}
