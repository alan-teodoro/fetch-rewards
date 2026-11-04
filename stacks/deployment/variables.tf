# One typed input tree feeds one root module and one Terraform state.
# Optional defaults mirror the leaf modules so their standalone behavior is kept.
# Credentials are separate: sensitive values must never determine for_each keys.
variable "subscription" {
  description = "Normalized subscription from the versioned JSON. Map keys are stable Terraform identities."
  type = object({
    mode                         = string
    subscription_id              = optional(number)
    subscription_name            = optional(string)
    dataset_size_in_gb           = optional(number, 1)
    cloud_provider               = optional(string, "AWS")
    region                       = optional(string, "us-east-1")
    networking_deployment_cidr   = optional(string, "10.80.0.0/24")
    multiple_availability_zones  = optional(bool, true)
    preferred_availability_zones = optional(list(string), [])
    public_endpoint_access       = optional(bool, false)
    memory_storage               = optional(string, "ram")
    payment_method               = optional(string, "credit-card")
    payment_method_id            = optional(string)
    payment_card_type            = optional(string)
    payment_card_last_four       = optional(string)
    throughput_ops_per_second    = optional(number, 1000)
    replication                  = optional(bool, true)
    support_oss_cluster_api      = optional(bool, false)
    modules                      = optional(list(string), [])
    maintenance_windows = optional(object({
      mode = string
      window = optional(object({
        start_hour        = number
        duration_in_hours = number
        days              = list(string)
      }))
    }))
    tags                 = optional(map(string), {})
    enable_resource_tags = optional(bool, false)
  })

  validation {
    condition     = contains(["managed", "external"], var.subscription.mode)
    error_message = "Resource mode must be managed or external."
  }
}

variable "databases" {
  description = "Normalized databases from the versioned JSON. Map keys are stable Terraform identities."
  type = map(object({
    mode                                  = string
    database_id                           = optional(number)
    database_name                         = optional(string)
    dataset_size_in_gb                    = optional(number, 1)
    redis_version                         = optional(string)
    throughput_ops_per_second             = optional(number, 1000)
    replication                           = optional(bool, true)
    enable_tls                            = optional(bool, true)
    enable_default_user                   = optional(bool, false)
    auto_minor_version_upgrade            = optional(bool, true)
    support_oss_cluster_api               = optional(bool, false)
    external_endpoint_for_oss_cluster_api = optional(bool, false)
    persistence_mode                      = optional(string, "aof-every-1-second")
    data_eviction                         = optional(string, "allkeys-lru")
    source_ips                            = optional(list(string))
    alerts = optional(list(object({
      name  = string
      value = number
    })), [])
    remote_backup = optional(object({
      interval     = string
      time_utc     = optional(string)
      storage_type = string
      storage_path = string
    }))
    acl_rule_string            = optional(string, "+@all -@dangerous +info ~*")
    acl_user_password_override = optional(string)
    tags                       = optional(map(string), {})
    enable_resource_tags       = optional(bool, false)
  }))
  default = {}
  validation {
    condition     = alltrue([for item in var.databases : contains(["managed", "external"], item.mode)])
    error_message = "Resource mode must be managed or external."
  }
}

variable "agent_memory_stores" {
  description = "Normalized agent_memory_stores from the versioned JSON. Map keys are stable Terraform identities."
  type = map(object({
    mode                       = string
    database_key               = optional(string)
    database_id                = optional(number)
    agent_memory_name          = optional(string)
    short_term_ttl_seconds     = optional(number)
    long_term_ttl_seconds      = optional(number)
    extraction_cadence_seconds = optional(number)
    extraction_strategy        = optional(string)
    timeouts = optional(object({
      create = optional(string)
      read   = optional(string)
      update = optional(string)
      delete = optional(string)
    }))
    llm = optional(object({
      provider = string
      model    = string
      credentials = optional(object({
        type            = optional(string, "apiKey")
        api_key_version = optional(number, 1)
      }))
    }))
    embedding = optional(object({
      provider = string
      model    = string
      credentials = optional(object({
        type            = optional(string, "apiKey")
        api_key_version = optional(number, 1)
      }))
    }))
    summarization = optional(object({
      enabled          = bool
      trigger_strategy = optional(string)
      event_count = optional(object({
        threshold    = number
        retain_count = number
      }))
    }))
    custom_memory_types = optional(list(object({
      name        = string
      description = string
      fields = optional(list(object({
        name        = string
        description = string
        type        = string
      })), [])
      extraction_strategy = optional(object({
        enabled = optional(bool)
        prompt  = string
      }))
    })), [])
    long_term_memory_exclusions = optional(object({
      enabled = bool # Master switch; family and detector switches are below.

      # Advisory guidance; provide a prompt when this family is enabled.
      semantic = optional(object({
        enabled = bool
        prompt  = optional(string)
      }))

      # IDs select API-provided detectors; [] means no configured detectors.
      # An omitted action delegates its default to the provider/API.
      built_in_detectors = optional(object({
        enabled = bool
        detectors = optional(list(object({
          id      = string
          enabled = bool
          action  = optional(string)
        })), [])
      }))

      # Each named rule carries its own regex and action (redact or drop).
      # The optional regex object preserves the API matcher shape; it must be
      # supplied for a regex matcher rather than inferred from its name.
      custom_detectors = optional(object({
        enabled = bool
        detectors = optional(list(object({
          name    = string
          enabled = bool
          action  = optional(string)
          matcher = object({
            kind = string
            regex = optional(object({
              pattern = string
            }))
          })
        })), [])
      }))
    }))
    api_keys = optional(map(object({
      name    = optional(string)
      enabled = optional(bool, true)
      timeouts = optional(object({
        create = optional(string)
        read   = optional(string)
        delete = optional(string)
      }))
    })), {})
    tags = optional(map(string), {})
  }))
  default = {}
  validation {
    condition     = alltrue([for item in var.agent_memory_stores : contains(["managed", "external"], item.mode)])
    error_message = "Resource mode must be managed or external."
  }
}

variable "model_api_keys" {
  description = "Sensitive model keys indexed by Agent Memory key; supplied separately from resource identities."
  type        = map(object({ llm_api_key = optional(string), embedding_api_key = optional(string) }))
  default     = {}
  sensitive   = true
}
