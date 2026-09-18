variable "subscription_name" {
  description = "Existing Redis Cloud subscription name. Terraform normalizes this to lowercase hyphen-separated format."
  type        = string
}

variable "database_name" {
  description = "Redis Cloud database name. Terraform normalizes this to lowercase hyphen-separated format."
  type        = string
}

variable "dataset_size_in_gb" {
  description = "Database dataset size in GB."
  type        = number
  default     = 1

  validation {
    condition     = var.dataset_size_in_gb > 0 && floor(var.dataset_size_in_gb) == var.dataset_size_in_gb
    error_message = "dataset_size_in_gb must be a positive integer."
  }
}

variable "redis_version" {
  description = "Optional Redis database version requested for this database. Leave null to use the Redis Cloud default."
  type        = string
  default     = null
}

variable "throughput_ops_per_second" {
  description = "Database throughput in operations per second."
  type        = number
  default     = 1000

  validation {
    condition     = var.throughput_ops_per_second > 0 && floor(var.throughput_ops_per_second) == var.throughput_ops_per_second
    error_message = "throughput_ops_per_second must be a positive integer."
  }
}

variable "replication" {
  description = "Whether Redis Cloud should create a replica for high availability."
  type        = bool
  default     = true
}

variable "enable_tls" {
  description = "Whether client connections to the database must use TLS."
  type        = bool
  default     = true
}

variable "enable_default_user" {
  description = "Whether to keep the built-in default database user enabled."
  type        = bool
  default     = false
}

variable "auto_minor_version_upgrade" {
  description = "Whether Redis Cloud may automatically apply minor Redis version upgrades."
  type        = bool
  default     = true
}

variable "support_oss_cluster_api" {
  description = "Whether to enable Redis OSS Cluster API compatibility."
  type        = bool
  default     = false
}

variable "external_endpoint_for_oss_cluster_api" {
  description = "Whether the OSS Cluster API should use the external endpoint. Requires support_oss_cluster_api."
  type        = bool
  default     = false
}

variable "persistence_mode" {
  description = "Database persistence mode."
  type        = string
  default     = "aof-every-1-second"

  validation {
    condition = contains([
      "none",
      "aof-every-1-second",
      "aof-every-write",
      "snapshot-every-1-hour",
      "snapshot-every-6-hours",
      "snapshot-every-12-hours"
    ], var.persistence_mode)
    error_message = "persistence_mode must be one of none, aof-every-1-second, aof-every-write, snapshot-every-1-hour, snapshot-every-6-hours, or snapshot-every-12-hours."
  }
}

variable "data_eviction" {
  description = "Database eviction policy."
  type        = string
  default     = "allkeys-lru"

  validation {
    condition = contains([
      "allkeys-lru",
      "allkeys-lfu",
      "allkeys-random",
      "volatile-lru",
      "volatile-lfu",
      "volatile-random",
      "volatile-ttl",
      "noeviction"
    ], var.data_eviction)
    error_message = "data_eviction must be one of allkeys-lru, allkeys-lfu, allkeys-random, volatile-lru, volatile-lfu, volatile-random, volatile-ttl, or noeviction."
  }
}

variable "source_ips" {
  description = "Optional source IP allowlist for public endpoint access."
  type        = list(string)
  default     = null
}

variable "alerts" {
  description = "Redis Cloud alert thresholds to configure on the database."
  type = list(object({
    name  = string
    value = number
  }))
  default = []

  validation {
    condition = alltrue([
      for alert in var.alerts : contains([
        "dataset-size",
        "datasets-size",
        "throughput-higher-than",
        "throughput-lower-than",
        "latency",
        "syncsource-error",
        "syncsource-lag",
        "connections-limit"
      ], alert.name)
    ])
    error_message = "alerts[*].name must be a supported Redis Cloud alert name."
  }
}

variable "remote_backup" {
  description = "Optional Redis Cloud remote backup configuration."
  type = object({
    interval     = string
    time_utc     = optional(string)
    storage_type = string
    storage_path = string
  })
  default = null

  validation {
    condition = var.remote_backup == null || contains([
      "every-1-hours",
      "every-2-hours",
      "every-4-hours",
      "every-6-hours",
      "every-12-hours",
      "every-24-hours"
    ], var.remote_backup.interval)
    error_message = "remote_backup.interval must be every-1-hours, every-2-hours, every-4-hours, every-6-hours, every-12-hours, or every-24-hours."
  }
}

variable "acl_rule_string" {
  description = "Redis ACL rule string for the application user."
  type        = string
  default     = "+@all -@dangerous +info ~*"
}

variable "acl_user_password_override" {
  description = "Optional explicit ACL user password. Leave null to generate one."
  type        = string
  default     = null
  sensitive   = true
}

variable "tags" {
  description = "Additional tags for Redis Cloud resources when enable_resource_tags is true."
  type        = map(string)
  default     = {}
}

variable "enable_resource_tags" {
  description = "Whether to send Redis Cloud resource tags. Keep false for internal Redis Cloud accounts."
  type        = bool
  default     = false
}
