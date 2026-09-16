variable "subscription_name" {
  description = "Redis Cloud subscription name."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.subscription_name))
    error_message = "subscription_name must be lowercase, hyphen-separated, and 3 to 63 characters long."
  }
}

variable "dataset_size_in_gb" {
  description = "Dataset size in GB used for the subscription creation plan envelope."
  type        = number
  default     = 1

  validation {
    condition     = var.dataset_size_in_gb > 0 && floor(var.dataset_size_in_gb) == var.dataset_size_in_gb
    error_message = "dataset_size_in_gb must be a positive integer."
  }
}

variable "cloud_provider" {
  description = "Cloud provider for the Redis Cloud subscription."
  type        = string
  default     = "AWS"

  validation {
    condition     = contains(["AWS", "GCP"], var.cloud_provider)
    error_message = "cloud_provider must be AWS or GCP."
  }
}

variable "region" {
  description = "Cloud provider region for the Redis Cloud subscription."
  type        = string
  default     = "us-east-1"
}

variable "networking_deployment_cidr" {
  description = "CIDR block Redis Cloud uses for the subscription deployment."
  type        = string
  default     = "10.80.0.0/24"

  validation {
    condition     = can(cidrhost(var.networking_deployment_cidr, 0))
    error_message = "networking_deployment_cidr must be a valid CIDR block."
  }
}

variable "multiple_availability_zones" {
  description = "Whether to deploy the subscription across multiple availability zones."
  type        = bool
  default     = false
}

variable "preferred_availability_zones" {
  description = "Optional preferred availability zones for multi-AZ subscriptions."
  type        = list(string)
  default     = []
}

variable "public_endpoint_access" {
  description = "Whether databases in this subscription may expose public endpoints."
  type        = bool
  default     = false
}

variable "memory_storage" {
  description = "Memory storage preference for the subscription."
  type        = string
  default     = "ram"

  validation {
    condition     = contains(["ram", "ram-and-flash"], var.memory_storage)
    error_message = "memory_storage must be ram or ram-and-flash."
  }
}

variable "payment_method" {
  description = "Optional Redis Cloud payment method. Leave null for direct contract or invoiced billing."
  type        = string
  default     = null

  validation {
    condition     = var.payment_method == null || contains(["credit-card", "marketplace"], var.payment_method)
    error_message = "payment_method must be null, credit-card, or marketplace."
  }
}

variable "payment_method_id" {
  description = "Optional Redis Cloud payment method ID. Required by Redis Cloud when payment_method is credit-card."
  type        = string
  default     = null
}

variable "throughput_ops_per_second" {
  description = "Throughput in operations per second used for the subscription creation plan envelope."
  type        = number
  default     = 5000

  validation {
    condition     = var.throughput_ops_per_second > 0 && floor(var.throughput_ops_per_second) == var.throughput_ops_per_second
    error_message = "throughput_ops_per_second must be a positive integer."
  }
}

variable "replication" {
  description = "Whether the subscription creation plan should assume replicated databases."
  type        = bool
  default     = true
}

variable "support_oss_cluster_api" {
  description = "Whether the subscription creation plan should assume OSS Cluster API support."
  type        = bool
  default     = false
}

variable "modules" {
  description = "Redis modules to include in the creation plan. Do not set modules for Redis 8 or newer databases."
  type        = list(string)
  default     = []
}

variable "maintenance_windows" {
  description = "Optional Redis Cloud maintenance window configuration."
  type = object({
    mode = string
    window = optional(object({
      start_hour        = number
      duration_in_hours = number
      days              = list(string)
    }))
  })
  default = null

  validation {
    condition     = var.maintenance_windows == null || contains(["automatic", "manual"], var.maintenance_windows.mode)
    error_message = "maintenance_windows.mode must be automatic or manual."
  }
}

variable "tags" {
  description = "Additional tags for supported resources."
  type        = map(string)
  default     = {}
}
