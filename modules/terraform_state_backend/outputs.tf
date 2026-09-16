output "bucket_name" {
  description = "Terraform state bucket name."
  value       = var.bucket_name
}

output "bucket_arn" {
  description = "Terraform state bucket ARN."
  value       = "arn:aws:s3:::${var.bucket_name}"
}

output "backend_access_policy_name" {
  description = "Inline IAM policy name attached to the GitHub Actions roles."
  value       = "terraform-state-${substr(sha1(var.bucket_name), 0, 12)}"
}

output "managed_github_actions_role_arns" {
  description = "Managed GitHub Actions OIDC role ARNs keyed by environment."
  value = {
    for environment, role in aws_iam_role.github_actions : environment => role.arn
  }
}

output "managed_github_actions_role_names" {
  description = "Managed GitHub Actions OIDC role names keyed by environment."
  value = {
    for environment, role in aws_iam_role.github_actions : environment => role.name
  }
}

output "github_oidc_provider_arn" {
  description = "GitHub OIDC provider ARN used in managed role trust policies."
  value       = local.github_oidc_provider_arn
}

output "managed_github_oidc_provider_arn" {
  description = "Managed GitHub OIDC provider ARN when create_github_oidc_provider is enabled."
  value       = try(aws_iam_openid_connect_provider.github[0].arn, null)
}
