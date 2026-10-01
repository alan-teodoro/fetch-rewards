resource "terraform_data" "validation" {
  lifecycle {
    precondition {
      condition     = !local.lookup_database || var.subscription_id != null || local.subscription_name != null
      error_message = "subscription_name or subscription_id is required when database_id is omitted."
    }

    precondition {
      condition     = local.subscription_name == null || can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", local.subscription_name))
      error_message = "subscription_name must normalize to a lowercase, hyphen-separated name that is 3 to 63 characters long."
    }

    precondition {
      condition     = !local.lookup_database || (local.database_name != null && can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", local.database_name)))
      error_message = "database_name must normalize to a lowercase, hyphen-separated name that is 3 to 63 characters long when database_id is omitted."
    }

    precondition {
      condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", local.agent_memory_name))
      error_message = "agent_memory_name must normalize to a lowercase, hyphen-separated name that is 3 to 63 characters long."
    }

    precondition {
      condition     = (var.llm == null && var.embedding == null) || (var.llm != null && var.embedding != null)
      error_message = "llm and embedding must be configured together for customer-managed Agent Memory models."
    }

    precondition {
      condition     = var.llm == null || (var.llm_api_key != null && var.embedding_api_key != null)
      error_message = "llm_api_key and embedding_api_key are required when customer-managed Agent Memory models are configured."
    }

    precondition {
      condition     = var.embedding == null || var.long_term_ttl_seconds != null
      error_message = "long_term_ttl_seconds is required when embedding is configured."
    }
  }
}

data "rediscloud_subscription" "target" {
  count = local.lookup_subscription ? 1 : 0

  depends_on = [terraform_data.validation]

  name = local.subscription_name
}

data "rediscloud_database" "target" {
  count = local.lookup_database ? 1 : 0

  depends_on = [terraform_data.validation]

  subscription_id = local.resolved_subscription_id
  name            = local.database_name
}

resource "terraform_data" "agent_memory_database_validation" {
  count = local.lookup_database ? 1 : 0

  lifecycle {
    precondition {
      condition     = data.rediscloud_database.target[0].enable_default_user
      error_message = "Redis Agent Memory currently requires the backing database default user to be enabled."
    }
  }
}

resource "rediscloud_agent_memory" "this" {
  depends_on = [
    terraform_data.validation,
    terraform_data.agent_memory_database_validation,
  ]

  name                       = local.agent_memory_name
  database_id                = local.resolved_database_id
  short_term_ttl_seconds     = var.short_term_ttl_seconds
  long_term_ttl_seconds      = var.long_term_ttl_seconds
  extraction_cadence_seconds = var.extraction_cadence_seconds

  dynamic "llm" {
    for_each = var.llm == null ? [] : [var.llm]

    content {
      provider = llm.value.provider
      model    = llm.value.model

      credentials {
        type    = coalesce(try(llm.value.credentials.type, null), "apiKey")
        api_key = var.llm_api_key
      }
    }
  }

  dynamic "embedding" {
    for_each = var.embedding == null ? [] : [var.embedding]

    content {
      provider = embedding.value.provider
      model    = embedding.value.model

      credentials {
        type    = coalesce(try(embedding.value.credentials.type, null), "apiKey")
        api_key = var.embedding_api_key
      }
    }
  }

  dynamic "summarization" {
    for_each = var.summarization == null ? [] : [var.summarization]

    content {
      enabled          = summarization.value.enabled
      trigger_strategy = summarization.value.trigger_strategy

      dynamic "event_count" {
        for_each = summarization.value.event_count == null ? [] : [summarization.value.event_count]

        content {
          threshold    = event_count.value.threshold
          retain_count = event_count.value.retain_count
        }
      }
    }
  }

  dynamic "custom_memory_types" {
    for_each = var.custom_memory_types

    content {
      name        = custom_memory_types.value.name
      description = custom_memory_types.value.description

      dynamic "fields" {
        for_each = custom_memory_types.value.fields

        content {
          name        = fields.value.name
          description = fields.value.description
          type        = fields.value.type
        }
      }

      dynamic "extraction_strategy" {
        for_each = custom_memory_types.value.extraction_strategy == null ? [] : [custom_memory_types.value.extraction_strategy]

        content {
          enabled = extraction_strategy.value.enabled
          prompt  = extraction_strategy.value.prompt
        }
      }
    }
  }

  dynamic "long_term_memory_exclusions" {
    for_each = var.long_term_memory_exclusions == null ? [] : [var.long_term_memory_exclusions]

    content {
      enabled = long_term_memory_exclusions.value.enabled

      dynamic "semantic" {
        for_each = long_term_memory_exclusions.value.semantic == null ? [] : [long_term_memory_exclusions.value.semantic]

        content {
          enabled = semantic.value.enabled
          prompt  = semantic.value.prompt
        }
      }

      dynamic "built_in_detectors" {
        for_each = long_term_memory_exclusions.value.built_in_detectors == null ? [] : [long_term_memory_exclusions.value.built_in_detectors]

        content {
          enabled = built_in_detectors.value.enabled

          dynamic "detectors" {
            for_each = built_in_detectors.value.detectors

            content {
              id      = detectors.value.id
              enabled = detectors.value.enabled
              action  = detectors.value.action
            }
          }
        }
      }

      dynamic "custom_detectors" {
        for_each = long_term_memory_exclusions.value.custom_detectors == null ? [] : [long_term_memory_exclusions.value.custom_detectors]

        content {
          enabled = custom_detectors.value.enabled

          dynamic "detectors" {
            for_each = custom_detectors.value.detectors

            content {
              name    = detectors.value.name
              enabled = detectors.value.enabled
              action  = detectors.value.action

              matcher {
                kind = detectors.value.matcher.kind

                dynamic "regex" {
                  for_each = detectors.value.matcher.regex == null ? [] : [detectors.value.matcher.regex]

                  content {
                    pattern = regex.value.pattern
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

resource "rediscloud_agent_memory_api_key" "this" {
  for_each = local.enabled_api_keys

  store_id = rediscloud_agent_memory.this.id
  name     = coalesce(each.value.name, each.key)
}
