# Resolve an existing billing method only for credit-card billing without an
# explicit ID. This reads account configuration; it never creates a payment card.
data "rediscloud_payment_method" "card" {
  count = local.can_lookup_payment_card ? 1 : 0

  card_type         = var.payment_card_type
  last_four_numbers = var.payment_card_last_four
}

# Local cross-input checks gate subscription creation. The name regex matches
# the complete normalized name (3-63 characters, alphanumeric at both ends).
# A validation resource is state bookkeeping, not an additional subscription.
resource "terraform_data" "validation" {
  lifecycle {
    precondition {
      condition     = !local.use_credit_card || var.payment_method_id != null || local.can_lookup_payment_card
      error_message = "Set payment_method_id or both payment_card_type and payment_card_last_four for credit-card billing."
    }

    precondition {
      condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", local.subscription_name))
      error_message = "subscription_name must normalize to a lowercase, hyphen-separated name that is 3 to 63 characters long."
    }
  }
}

resource "rediscloud_subscription" "this" {
  depends_on = [terraform_data.validation]

  name                   = local.subscription_name
  payment_method         = local.use_marketplace ? "marketplace" : null
  payment_method_id      = local.resolved_payment_method_id
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

  # This is the subscription's initial capacity envelope. Actual databases
  # are declared by the database module, not by this nested block.
  creation_plan {
    dataset_size_in_gb           = var.dataset_size_in_gb
    quantity                     = 1
    replication                  = local.replication
    support_oss_cluster_api      = local.support_oss_cluster_api
    throughput_measurement_by    = local.throughput_measurement_by
    throughput_measurement_value = var.throughput_ops_per_second
    modules                      = local.modules
  }

  # Optional objects use []/[object] to emit zero/one blocks. An automatic
  # policy can omit window; a manual policy supplies its scheduled window.
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

  # Check the resolved billing result as well as the supplied selector. An ID
  # obtained by a data source may only become known during apply.
  lifecycle {
    precondition {
      condition     = !local.use_credit_card || local.resolved_payment_method_id != null
      error_message = "When payment_method is credit-card, provide payment_method_id or a valid payment_card_type and payment_card_last_four pair."
    }
  }
}
