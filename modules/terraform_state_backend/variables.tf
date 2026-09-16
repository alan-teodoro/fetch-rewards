variable "bucket_name" {
  description = "Name of the S3 bucket that stores Terraform state."
  type        = string
}

variable "github_actions_role_arns" {
  description = "Existing GitHub Actions IAM role ARNs that should access the Terraform state bucket."
  type        = set(string)
  default     = []
}

variable "create_github_actions_roles" {
  description = "Whether to create GitHub Actions OIDC IAM roles for this repository."
  type        = bool
  default     = false
}

variable "create_github_oidc_provider" {
  description = "Whether to create the standard GitHub OIDC provider in the target AWS account."
  type        = bool
  default     = false
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN in the target AWS account. Defaults to the standard provider ARN in the current AWS account."
  type        = string
  default     = null
}

variable "github_repository_owner" {
  description = "GitHub organization or user that owns the repository allowed to assume the managed OIDC roles."
  type        = string
  default     = null
}

variable "github_repository_name" {
  description = "GitHub repository name allowed to assume the managed OIDC roles."
  type        = string
  default     = null
}

variable "github_allowed_branches" {
  description = "Branches that may assume the managed OIDC roles outside GitHub environments."
  type        = set(string)
  default     = ["main"]
}

variable "github_actions_role_names_by_environment" {
  description = "Role names to create for each GitHub Actions environment when create_github_actions_roles is enabled."
  type        = map(string)
  default = {
    prod = "GitHubActionsOIDCRedisCloudProd"
  }
}

variable "allowed_state_prefixes" {
  description = "S3 object key prefixes that GitHub Actions may manage in the state bucket."
  type        = set(string)
  default = [
    "subscriptions/*",
    "databases/*",
    "agent-memory/*"
  ]
}

variable "enable_versioning" {
  description = "Whether to enable bucket versioning."
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Whether Terraform may destroy a non-empty state bucket."
  type        = bool
  default     = false
}

variable "kms_key_arn" {
  description = "Optional KMS key ARN for bucket encryption. Defaults to S3-managed AES256 encryption."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to backend resources."
  type        = map(string)
  default     = {}
}
