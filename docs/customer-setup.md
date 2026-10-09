# Customer Setup Guide

This guide describes how to install and operate the Redis Cloud automation repository in a customer-owned GitHub organization.

## 1. Copy the Repository

Create a new customer repository and copy this project into it. Keep the directory layout unchanged because the workflows reference the stack paths directly.

## 2. Create Redis Cloud API Keys

Create Redis Cloud programmatic API keys with permission to manage Pro subscriptions, databases, ACL rules, roles, and users.

Add these GitHub repository secrets:

```text
REDISCLOUD_ACCESS_KEY
REDISCLOUD_SECRET_KEY
```

For non-public Redis Cloud API environments, also set `REDISCLOUD_URL` as a
repository variable or secret. Leave it unset for the public Redis Cloud API.

If Agent Memory uses customer-managed LLM and embedding providers, add the
model provider secrets referenced by the config files. The default examples use:

```text
AGENT_MEMORY_LLM_API_KEY
AGENT_MEMORY_EMBEDDING_API_KEY
```

## 3. Bootstrap AWS Remote State and OIDC

The Redis Cloud workflow uses an S3 bucket for Terraform state and a GitHub Actions OIDC IAM role to access that bucket.

Run the backend stack once from an administrator workstation that has AWS credentials and the AWS CLI installed:

```bash
cd stacks/state-backend
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region  = "us-east-1"
bucket_name = "customer-rediscloud-terraform-state"

create_github_oidc_provider = true
create_github_actions_roles = true
github_actions_role_arns    = []
github_repository_owner     = "customer-github-org"
github_repository_name      = "redis-cloud-automation"
github_allowed_branches     = ["main"]

github_actions_role_names_by_environment = {
  prod = "GitHubActionsOIDCRedisCloudProd"
}
```

Then apply:

```bash
terraform init
terraform apply
```

If the AWS account already has the standard GitHub OIDC provider, set `create_github_oidc_provider = false` and either provide `github_oidc_provider_arn` or let the stack use the standard ARN path for the current account.

The backend stack grants S3 state access through a customer-managed IAM policy attached to the GitHub Actions role. Avoid adding this access as an inline role policy when reusing a shared OIDC role across repositories, because AWS applies a small total-size limit to inline policies on a role.

## 4. Configure GitHub Repository Settings

Add these GitHub repository variables:

```text
TF_STATE_BUCKET
TF_STATE_REGION
```

Set `TF_STATE_BUCKET` to the `bucket_name` output and `TF_STATE_REGION` to the backend AWS region.

Add this GitHub repository or environment variable:

```text
AWS_GITHUB_ACTIONS_ROLE_ARN
```

Set it to the `managed_github_actions_role_arns.prod` output, or to an existing OIDC role ARN if the customer manages roles separately.

The workflows assume a single GitHub Actions OIDC role, stored in `AWS_GITHUB_ACTIONS_ROLE_ARN`. GitHub environments are not required for OIDC.

Create a GitHub environment named `dev` and configure required reviewers for
it. The **Redis Cloud Config Destroy** workflow always uses this environment
before destroying resources. The **Redis Cloud Config Apply** workflow blocks
Agent Memory delete/replace plans; use the destroy workflow for intentional
destructive cleanup.

The subscription stack defaults to Redis Cloud credit-card billing and looks up the saved payment method by card type and last four digits, matching the current PS test account baseline. For a customer account, update the defaults in `stacks/subscription/variables.tf` or override them with repository variables.

For the GitHub workflow path, use optional repository variables instead:

```text
REDISCLOUD_PAYMENT_METHOD
REDISCLOUD_PAYMENT_METHOD_ID
REDISCLOUD_PAYMENT_CARD_TYPE
REDISCLOUD_PAYMENT_CARD_LAST_FOUR
```

For credit-card billing, either set `REDISCLOUD_PAYMENT_METHOD_ID` to the Redis Cloud payment method ID, or set `REDISCLOUD_PAYMENT_CARD_TYPE` and `REDISCLOUD_PAYMENT_CARD_LAST_FOUR` so Terraform can look it up. Leave these unset only for direct contract or invoiced accounts when Redis Cloud does not require payment information.

Redis Cloud resource tags are not exposed in the manual workflows. They remain disabled by default because internal Redis Cloud cloud accounts do not allow them. Enable `enable_resource_tags` only through Terraform defaults for customer accounts where Redis Cloud supports resource tagging.

For the config-driven Agent Memory PoC, the workflows can build the Redis Cloud
provider from the Agent Memory branch before running Terraform. The provider
repository is fixed in the workflow; the default workflow inputs use:

```text
rediscloud_provider_source     = branch
rediscloud_provider_ref        = alan/agent-memory-terraform-provider
```

If that provider branch is private, add a repository secret named
`REDISCLOUD_PROVIDER_CHECKOUT_TOKEN` with read access to the provider
repository.

For validation runs, these optional repository variables can override the same
provider source/ref defaults:

```text
REDISCLOUD_PROVIDER_SOURCE
REDISCLOUD_PROVIDER_REF
```

Set `REDISCLOUD_PROVIDER_SOURCE = registry` once the official Redis Cloud
provider release includes `rediscloud_agent_memory` and
`rediscloud_agent_memory_api_key`.

## 5. Validate the Repository

Run the validation workflow, or run locally:

```bash
terraform fmt -check -recursive

for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done

python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

While Agent Memory support depends on the provider branch, the validation
workflow builds that branch and validates `stacks/agent-memory` automatically.

## 6. Provision or Update Resources

Run **Actions > Redis Cloud Config Apply > Run workflow**.

Use the [Demo Guide](demo-guide.md) as the demo checklist and talk track.

Common inputs:

- `config_path`: path to one subscription config file, for example `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`.
- `operation`: `plan` or `apply`.
- `rediscloud_provider_source`: keep `branch` while Agent Memory support is unreleased; switch to `registry` after the official provider includes the Agent Memory resources.
- `rediscloud_provider_ref`: provider branch, tag, or commit used only when `rediscloud_provider_source` is `branch`.

The config-driven workflow renders Terraform tfvars from the JSON file and runs stacks in dependency phases:

1. `stacks/subscription`
2. `stacks/database`
3. `stacks/agent-memory`

In `apply` mode, each phase is fully planned before the saved plans for that
phase are applied. This catches plan failures across all databases before any
database is applied, and catches Agent Memory plan or destroy-guard failures
before any Agent Memory service is applied.

The workflow supports managed and external resources in the same file. Use `external` for existing subscriptions or databases that Terraform should reference but not create.

For external subscriptions, the config can include both `name` and
`subscription_id`. Use `subscription_id` when database creation should target an
existing subscription by ID instead of relying on Redis Cloud subscription
lookup by name.

Agent Memory API key values are not printed in workflow summaries. They are Terraform-sensitive and stored in the Agent Memory state. Use `secret_ref` in the config file to record where the generated data-plane key should be published by the runner or a follow-up secret publishing step.

Customer-managed LLM and embedding API keys are also not stored in JSON. The
config references environment variable names with `api_key_env_var`; the
workflow exposes the corresponding GitHub secrets to the renderer.

The official Redis Cloud provider currently does not include the Agent Memory
resources used by this PoC. Until it does, keep
`rediscloud_provider_source = branch` when running the config workflow.

## 7. Destroy Managed Resources

Run **Actions > Redis Cloud Config Destroy > Run workflow**.

Common inputs:

- `config_path`: the same subscription config file used for apply.
- `confirm_destroy`: must be `true`.
- `rediscloud_provider_source`: keep `branch` while Agent Memory support is unreleased; switch to `registry` after the official provider includes the Agent Memory resources.
- `rediscloud_provider_ref`: provider branch, tag, or commit used only when `rediscloud_provider_source` is `branch`.

The destroy workflow renders the config file and destroys only managed resources
described by that file. It runs in reverse dependency order:

1. Agent Memory services and their data-plane API keys.
2. Managed databases and their ACL resources.
3. The managed subscription, only when the config marks the subscription as
   `managed`.

External resources in the config are not destroyed. Before each destroy, the
workflow writes a Terraform destroy plan summary to the GitHub Actions summary
and then applies the saved destroy plan file. Use this workflow for explicit
cleanup instead of relying on implicit deletes from removing resources from the
JSON file.
