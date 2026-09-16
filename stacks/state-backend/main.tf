resource "terraform_data" "validation" {
  lifecycle {
    precondition {
      condition     = length(var.github_actions_role_arns) > 0 || var.create_github_actions_roles
      error_message = "Provide at least one existing github_actions_role_arn or enable create_github_actions_roles."
    }

    precondition {
      condition = !var.create_github_actions_roles || (
        coalesce(var.github_repository_owner, "") != "" &&
        coalesce(var.github_repository_name, "") != "" &&
        length(var.github_allowed_branches) > 0 &&
        length(var.github_actions_role_names_by_environment) > 0
      )
      error_message = "When create_github_actions_roles is true, github_repository_owner, github_repository_name, github_allowed_branches, and github_actions_role_names_by_environment must be provided."
    }

    precondition {
      condition     = !(var.create_github_oidc_provider && var.github_oidc_provider_arn != null && coalesce(var.github_oidc_provider_arn, "") != "")
      error_message = "Set either create_github_oidc_provider or github_oidc_provider_arn, not both."
    }
  }
}

module "state_backend" {
  source = "../../modules/terraform_state_backend"

  depends_on = [terraform_data.validation]

  bucket_name                              = var.bucket_name
  github_actions_role_arns                 = var.github_actions_role_arns
  create_github_actions_roles              = var.create_github_actions_roles
  create_github_oidc_provider              = var.create_github_oidc_provider
  github_oidc_provider_arn                 = var.github_oidc_provider_arn
  github_repository_owner                  = var.github_repository_owner
  github_repository_name                   = var.github_repository_name
  github_allowed_branches                  = var.github_allowed_branches
  github_actions_role_names_by_environment = var.github_actions_role_names_by_environment
  allowed_state_prefixes                   = var.allowed_state_prefixes
  enable_versioning                        = var.enable_versioning
  force_destroy                            = var.force_destroy
  kms_key_arn                              = var.kms_key_arn
  tags = merge(
    {
      managed_by = "terraform"
      customer   = "fetch-rewards"
      component  = "terraform-state-backend"
    },
    var.tags
  )
}
