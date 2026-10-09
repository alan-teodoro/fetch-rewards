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
QA/smoke-test credentials can be configured separately with:

```text
REDISCLOUD_ACCESS_KEY_QA
REDISCLOUD_SECRET_KEY_QA
REDISCLOUD_URL_QA
```

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

Create a GitHub environment named `dev` and configure required reviewers for it. The **Redis Cloud Create** workflow uses this environment only when the requested subscription does not already exist. The **Redis Cloud Destroy** workflow uses the same environment only when `destroy_subscription` is true. Database-only updates and destroys continue without this checkpoint.

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

For the config-driven Agent Memory PoC, the workflow can build the Redis Cloud
provider from the Agent Memory branch before running Terraform. The default
workflow inputs use:

```text
rediscloud_provider_source     = branch
rediscloud_provider_repository = RedisLabs/terraform-provider-rediscloud
rediscloud_provider_ref        = alan/agent-memory-terraform-provider
```

If that provider branch is private, add a repository secret named
`REDISCLOUD_PROVIDER_CHECKOUT_TOKEN` with read access to the provider
repository.

For validation runs, these optional repository variables can override the same
defaults:

```text
REDISCLOUD_PROVIDER_SOURCE
REDISCLOUD_PROVIDER_REPOSITORY
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

## 6. Provision or Update a Database

Run **Actions > Redis Cloud Create > Run workflow**.

Use this workflow for both common provisioning paths:

- If the normalized subscription name already exists in Redis Cloud, Terraform creates or updates only the database and ACL resources.
- If the normalized subscription name does not exist, the workflow waits for approval on the `dev` environment, then creates the subscription and database.

Common inputs:

- `subscription_name`
- `database_name`
- `subscription_region`
- `subscription_multi_az`
- `dataset_size_in_gb`
- `high_availability`
- `throughput_ops_per_second`
- `redis_version`
- `persistence_mode`
- `data_eviction`

The workflow accepts user-friendly names and normalizes them internally for Terraform state and Redis Cloud resources. For example, `Fetch Rewards Prod` becomes `fetch-rewards-prod`. The GitHub Actions summary shows both requested and normalized names.

`subscription_region` is limited to the supported US AWS regions exposed by the workflow: `us-east-1`, `us-east-2`, `us-west-1`, and `us-west-2`. `subscription_multi_az` defaults to `true`. These subscription inputs are used only when the workflow creates a new subscription.

The database inputs are treated as desired state. To update an existing managed database, run the same workflow again with the same normalized `subscription_name` and `database_name`, and provide the desired final values for every exposed setting.

The Redis version dropdown matches the console options currently exposed by the workflow: `6.2`, `7.2`, `7.4`, `8.2`, `8.4`, and `8.6`. Data persistence options are `none`, `aof-every-1-second`, `aof-every-write`, `snapshot-every-1-hour`, `snapshot-every-6-hours`, and `snapshot-every-12-hours`. Data eviction options are `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`, `volatile-random`, `volatile-ttl`, and `noeviction`.

Redis Flex is disabled, Redis-provided cloud accounts and new VPC deployment are used, maintenance windows stay automatic, and resource tags are not exposed in the workflow.

The workflow stores state under:

```text
subscriptions/<normalized_subscription_name>.tfstate
databases/<normalized_subscription_name>/<normalized_database_name>.tfstate
```

Before running Terraform, the workflow queries the Redis Cloud API:

- If the subscription does not exist, the workflow creates it.
- If the database already exists, Terraform imports it into the selected state when needed, then applies the requested settings.
- If the database does not exist, Terraform creates it.

Before each apply, the workflow writes a Terraform plan summary to the GitHub Actions summary and then applies the saved plan file.

## 7. Destroy Managed Resources

Run **Actions > Redis Cloud Destroy > Run workflow**.

Destroy only a database and its ACL resources:

```text
subscription_name = fetch-rewards-prod
database_name = session-cache
destroy_subscription = false
confirm_destroy = true
```

Destroy a database and its managed subscription when that database is the last one:

```text
subscription_name = fetch-rewards-prod
database_name = session-cache
destroy_subscription = true
confirm_destroy = true
```

The workflow checks Redis Cloud before running Terraform. If `destroy_subscription` is true, it blocks when the subscription has more than one database or when the requested database is not the last database in that subscription. The subscription destroy path waits for approval on the `dev` environment.

Before each destroy, the workflow writes a Terraform destroy plan summary to the GitHub Actions summary and then applies the saved destroy plan file. Database state is stored under `databases/<normalized_subscription_name>/<normalized_database_name>.tfstate`. Subscription state is stored under `subscriptions/<normalized_subscription_name>.tfstate`. Only use `destroy_subscription = true` for subscriptions managed by this repository.

## 8. Config-Driven Agent Memory PoC

Run **Actions > Redis Cloud Config Apply > Run workflow**.

Use the [Demo Guide](demo-guide.md) as the demo checklist and talk track.

Common inputs:

- `config_path`: path to one subscription config file, for example `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`.
- `operation`: `plan` or `apply`.
- `credentials_profile`: `default` uses `REDISCLOUD_ACCESS_KEY` and `REDISCLOUD_SECRET_KEY`; `qa` uses the `*_QA` credentials and optional `REDISCLOUD_URL_QA`.
- `allow_agent_memory_destroy`: keep `false` unless a destructive Agent Memory change has been explicitly approved.
- `rediscloud_provider_source`: keep `branch` during the PoC; switch to `registry` after the Agent Memory provider is officially released.

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
