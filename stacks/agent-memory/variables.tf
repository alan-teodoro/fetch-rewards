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

variable "short_term_ttl_seconds" {
  description = "Short-term memory TTL in seconds. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.short_term_ttl_seconds == null || (var.short_term_ttl_seconds >= 1 && var.short_term_ttl_seconds <= 31536000)
    error_message = "short_term_ttl_seconds must be between 1 and 31536000."
  }
}

variable "long_term_ttl_seconds" {
  description = "Long-term memory TTL in seconds. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.long_term_ttl_seconds == null || (var.long_term_ttl_seconds >= 1 && var.long_term_ttl_seconds <= 31536000)
    error_message = "long_term_ttl_seconds must be between 1 and 31536000."
  }
}

variable "extraction_cadence_seconds" {
  description = "How often the extraction pipeline runs while a session is active. Leave null to use the Redis Cloud default."
  type        = number
  default     = null

  validation {
    condition     = var.extraction_cadence_seconds == null || (var.extraction_cadence_seconds >= 60 && var.extraction_cadence_seconds <= 600)
    error_message = "extraction_cadence_seconds must be between 60 and 600."
  }
}

variable "llm" {
  description = "Optional customer-managed LLM model configuration. Configure together with embedding when the store is created."
  type = object({
    provider = string
    model    = string
    credentials = optional(object({
      type = optional(string, "apiKey")
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
      type = optional(string, "apiKey")
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

variable "long_term_memory_exclusions" {
  description = "Optional policy defining content that must not be kept in long-term memory."
  type = object({
    enabled = bool
    semantic = optional(object({
      enabled = bool
      prompt  = optional(string)
    }))
    built_in_detectors = optional(object({
      enabled = bool
      detectors = optional(list(object({
        id      = string
        enabled = bool
        action  = optional(string)
      })), [])
    }))
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

variable "api_keys" {
  description = "Named data-plane API keys to create for this Agent Memory service. The generated secrets are stored in Terraform state as sensitive values."
  type = map(object({
    name    = optional(string)
    enabled = optional(bool, true)
  }))
  default = {}
}

variable "tags" {
  description = "Reserved for future Agent Memory tagging support."
  type        = map(string)
  default     = {}
}
