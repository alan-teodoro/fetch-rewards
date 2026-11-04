variable "subscription_name" {
  description = "Existing Redis Cloud subscription name. Required when database_id and subscription_id are omitted."
  type        = string
  default     = null
}

variable "subscription_id" {
  description = "Existing Redis Cloud subscription ID. Used to resolve database_name when database_id is omitted and subscription lookup by name is not desired."
  type        = number
  default     = null

  validation {
    condition     = var.subscription_id == null || var.subscription_id > 0
    error_message = "subscription_id must be greater than zero when provided."
  }
}

variable "database_name" {
  description = "Existing Redis Cloud database name backing the Agent Memory service. Required when database_id is omitted."
  type        = string
  default     = null
}

variable "database_id" {
  description = "Existing Redis Cloud database ID backing the Agent Memory service. When omitted, Terraform resolves the database by subscription_name and database_name."
  type        = number
  default     = null

  validation {
    condition     = var.database_id == null || var.database_id > 0
    error_message = "database_id must be greater than zero when provided."
  }
}

variable "agent_memory_name" {
  description = "Redis Agent Memory service name. Terraform normalizes this to lowercase hyphen-separated format."
  type        = string
}

# null leaves retention/cadence selection to the provider/API. These validators
# reject non-positive or fractional seconds without freezing evolving API limits.
variable "short_term_ttl_seconds" {
  description = "Short-term memory TTL in seconds. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.short_term_ttl_seconds == null || (var.short_term_ttl_seconds >= 1 && floor(var.short_term_ttl_seconds) == var.short_term_ttl_seconds)
    error_message = "short_term_ttl_seconds must be a positive integer. The API validates supported limits."
  }
}

variable "long_term_ttl_seconds" {
  description = "Long-term memory TTL in seconds. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.long_term_ttl_seconds == null || (var.long_term_ttl_seconds >= 1 && floor(var.long_term_ttl_seconds) == var.long_term_ttl_seconds)
    error_message = "long_term_ttl_seconds must be a positive integer. The API validates supported limits."
  }
}

variable "extraction_cadence_seconds" {
  description = "How often the extraction pipeline runs while a session is active. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.extraction_cadence_seconds == null || (var.extraction_cadence_seconds >= 1 && floor(var.extraction_cadence_seconds) == var.extraction_cadence_seconds)
    error_message = "extraction_cadence_seconds must be a positive integer. The API validates supported limits."
  }
}

variable "extraction_strategy" {
  description = "Optional extraction strategy accepted by the API. Changing a configured strategy replaces the store."
  type        = string
  default     = null
}

# These are operation wait budgets, not memory TTLs. Omitted members inherit
# provider defaults; the workflow's job timeout can end the operation earlier.
variable "timeouts" {
  description = "Optional operation timeouts using provider duration strings, such as 30m."
  type = object({
    create = optional(string)
    read   = optional(string)
    update = optional(string)
    delete = optional(string)
  })
  default = null
}

# Model identity is separate from the sensitive API key input. The version is
# a non-secret rotation counter: changing a write-only key alone creates no diff.
# embedding uses the same shape; the pair is checked together in main.tf.
variable "llm" {
  description = "Optional customer-managed LLM model configuration. Configure together with embedding when the store is created."
  type = object({
    provider = string
    model    = string
    credentials = optional(object({
      type            = optional(string, "apiKey")
      api_key_version = optional(number, 1)
    }))
  })
  default = null

  validation {
    condition     = var.llm == null || trimspace(var.llm.provider) != ""
    error_message = "llm.provider must be a non-empty string."
  }

  validation {
    condition     = var.llm == null || trimspace(var.llm.model) != ""
    error_message = "llm.model must be a non-empty string."
  }

  validation {
    condition     = var.llm == null || var.llm.credentials == null || var.llm.credentials.type == "apiKey"
    error_message = "llm.credentials.type must be apiKey when configured."
  }
}

variable "llm_api_key" {
  description = "Sensitive API key for the customer-managed LLM provider. Required when llm is configured."
  type        = string
  default     = null
  sensitive   = true
}

variable "embedding" {
  description = "Optional customer-managed embedding model configuration. Configure together with llm when the store is created."
  type = object({
    provider = string
    model    = string
    credentials = optional(object({
      type            = optional(string, "apiKey")
      api_key_version = optional(number, 1)
    }))
  })
  default = null

  validation {
    condition     = var.embedding == null || trimspace(var.embedding.provider) != ""
    error_message = "embedding.provider must be a non-empty string."
  }

  validation {
    condition     = var.embedding == null || trimspace(var.embedding.model) != ""
    error_message = "embedding.model must be a non-empty string."
  }

  validation {
    condition     = var.embedding == null || var.embedding.credentials == null || var.embedding.credentials.type == "apiKey"
    error_message = "embedding.credentials.type must be apiKey when configured."
  }
}

variable "embedding_api_key" {
  description = "Sensitive API key for the customer-managed embedding provider. Required when embedding is configured."
  type        = string
  default     = null
  sensitive   = true
}

# Keep the newest retain_count events verbatim when threshold is reached.
# For threshold = 20 and retain_count = 10, the older 10 are summarized.
# null omits the block; enabled = false explicitly requests summarization off.
variable "summarization" {
  description = "Optional Agent Memory session summarization configuration."
  type = object({
    enabled          = bool
    trigger_strategy = optional(string)
    event_count = optional(object({
      threshold    = number
      retain_count = number
    }))
  })
  default = null
}

# Each object describes one named memory type and its structured field schema.
# fields defaults to an empty list; extraction_strategy defaults to null.
# Its optional enabled flag deliberately has no local true/false default: an
# omitted value is resolved by the provider/API. See replacement notes in main.tf.
variable "custom_memory_types" {
  description = "Optional custom long-term memory types."
  type = list(object({
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
  }))
  default = []
}

# One policy object with three independently optional families. Omitting it
# (null) supplies no block; use explicit enabled = false to request disabling.
# Rules apply to newly extracted long-term memories, not session events,
# summaries, direct application writes or existing records. Semantic prompts
# guide extraction and do not guarantee that sensitive content is excluded.
# See docs/configuration-reference.md for the hierarchy and a JSON example.
variable "long_term_memory_exclusions" {
  description = "Optional exclusion rules for newly extracted long-term memories."
  type = object({
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
  })
  default = null
}

# These map keys are durable state identities, not list positions. enabled is
# an orchestration switch that controls resource existence; see main.tf.
variable "api_keys" {
  description = "Named data-plane API keys to create for this Agent Memory service. The generated secrets are stored in Terraform state as sensitive values."
  type = map(object({
    name    = optional(string)
    enabled = optional(bool, true)
    timeouts = optional(object({
      create = optional(string)
      read   = optional(string)
      delete = optional(string)
    }))
  }))
  default = {}
}

variable "tags" {
  description = "Reserved for future Agent Memory tagging support."
  type        = map(string)
  default     = {}
}

# The deployment root passes false when it supplies a parent's computed ID.
# Selecting by ID value alone would make lookup count unknown on the first plan.
variable "lookup_database" {
  description = "Optional explicit lookup selection for composition with managed parent resources."
  type        = bool
  default     = null
}
