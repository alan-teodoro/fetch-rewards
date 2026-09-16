output "bucket_name" {
  description = "Terraform state bucket name."
  value       = module.state_backend.bucket_name
}

output "bucket_arn" {
  description = "Terraform state bucket ARN."
  value       = module.state_backend.bucket_arn
}

output "backend_access_policy_name" {
  description = "Inline IAM policy name attached to the GitHub Actions roles."
  value       = module.state_backend.backend_access_policy_name
}

output "aws_region" {
  description = "AWS region used by the backend stack."
  value       = var.aws_region
}

output "managed_github_actions_role_arns" {
  description = "Managed GitHub Actions OIDC role ARNs keyed by environment."
  value       = module.state_backend.managed_github_actions_role_arns
}

output "managed_github_actions_role_names" {
  description = "Managed GitHub Actions OIDC role names keyed by environment."
  value       = module.state_backend.managed_github_actions_role_names
}

output "github_oidc_provider_arn" {
  description = "GitHub OIDC provider ARN used in managed role trust policies."
  value       = module.state_backend.github_oidc_provider_arn
}

output "managed_github_oidc_provider_arn" {
  description = "Managed GitHub OIDC provider ARN when create_github_oidc_provider is enabled."
  value       = module.state_backend.managed_github_oidc_provider_arn
}
